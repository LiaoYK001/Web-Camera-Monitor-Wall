import { expect, test, type Page } from '@playwright/test';
import type { NvrExportJob, NvrSegment } from '../../src/types';

const fixture = '/tests/harness/nvr-evidence.html';
const dayStart = Date.parse(`${new Date().toISOString().slice(0,10)}T00:00:00Z`);
const start = dayStart + 3600_000;
const segment: NvrSegment = { id: 'a'.repeat(32), cameraId: 'cam', startUtcMs: start, endUtcMs: start+30000,
  durationMs: 30000, kind:'continuous', videoCodec:'h264', audioCodec:'aac', sizeBytes:1024, integrity:'ok', locked:false,
  mediaUrl:'/api/v1/nvr/media/'+ 'a'.repeat(32) };

async function protocol(page: Page, options: { catalogFailure?: boolean } = {}) {
  const state = { jobs: [] as NvrExportJob[], submitted: 0, cancelled: 0, lost: false, delay: 0, denied:false,
    segments: [structuredClone(segment)], leases:0, released:0, deleted:0,
    timelineDelay: 0, timelineFailure: false, catalogFailure: !!options.catalogFailure, queries: 0 };
  await page.addInitScript(() => {
    Object.defineProperty(HTMLMediaElement.prototype,'duration',{get:()=>30});
    Object.defineProperty(HTMLMediaElement.prototype,'readyState',{get:()=>2});
    HTMLMediaElement.prototype.play = async function() {
      if ((window as unknown as { rejectPlayback:boolean }).rejectPlayback) throw new DOMException('blocked','NotAllowedError');
      if ((window as unknown as { holdPlayback:boolean }).holdPlayback) await new Promise<void>(resolve=>{
        (window as unknown as { releasePlayback:()=>void }).releasePlayback=resolve;
      });
      this.dataset.played='true';
    };
    HTMLMediaElement.prototype.pause=function() { this.dataset.played='false'; };
  });
  await page.route('**/api/**', async route => {
    const request=route.request(); const url=new URL(request.url()); const path=url.pathname;
    const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/v1/auth/session') return reply({authenticated:true,user:'fixture-admin'});
    if(path==='/api/v1/nvr/status') return state.catalogFailure ? reply({error:{code:'service_unavailable',message:'录像服务暂不可用'}},503) : reply({status:'ok',freeBytes:1e9,diskPressure:false,
      cameras:['cam','two','three','four','five'].map(id=>({id,policy:'continuous',state:'idle',segments:1,eventActive:false}))});
    if(path==='/api/v1/nvr/timeline') {
      state.queries++;
      const fail=state.timelineFailure;
      const document={fromUtcMs:dayStart,toUtcMs:dayStart+86400000,storageTimeZone:'UTC',queryDurationMs:2,
        cameras:url.searchParams.getAll('cameraId').map(cameraId=>({cameraId,recordedStream:'main',retentionBoundaryUtcMs:null,
          segments:cameraId==='cam'?state.segments:[],gaps:[]}))};
      if(state.timelineDelay)await new Promise(resolve=>setTimeout(resolve,state.timelineDelay));
      return fail ? reply({error:{code:'service_unavailable',message:'录像服务暂不可用'}},503) : reply(document);
    }
    if(path==='/api/v1/nvr/exports/jobs' && request.method()==='GET') return state.denied
      ? reply({error:{code:'permission_rejected',message:'role rejected'}},403) : reply({jobs:state.jobs});
    if(path==='/api/v1/nvr/exports/jobs' && request.method()==='POST') {
      state.submitted++;
      const {requestId,...data}=request.postDataJSON();
      const job:NvrExportJob={id:'b'.repeat(32),requestId,state:'queued',createdUtcMs:start,updatedUtcMs:start,request:data,result:null,error:null};
      state.jobs=[job];
      if(state.delay) await new Promise(resolve=>setTimeout(resolve,state.delay));
      if(state.lost) return route.abort('connectionfailed');
      return reply(job,202);
    }
    if(path.endsWith('/cancel')) { state.cancelled++;state.jobs[0]={...state.jobs[0],state:'cancelled'}; return reply(state.jobs[0]); }
    if(path==='/api/v1/nvr/playback-leases') { state.leases++;return reply({id:String(state.leases).padStart(32,'0'),segmentId:segment.id,expiresUtcMs:start+40000},201); }
    if(path.startsWith('/api/v1/nvr/playback-leases/')) { state.released++;return reply({released:true}); }
    if(path==='/api/v1/nvr/snapshots') return reply({id:'c'.repeat(32),sha256:'d'.repeat(64),downloadUrl:'/api/v1/nvr/downloads/'+ 'c'.repeat(32)+'.jpg'},201);
    if(path.startsWith('/api/v1/nvr/segments/') && request.method()==='DELETE') {state.deleted++;state.segments=[];return reply({deleted:true});}
    if(path.startsWith('/api/v1/nvr/locks/'))return reply({locked:true});
    return route.fulfill({status:404,body:''});
  });
  await page.goto(fixture);
  if (options.catalogFailure) { await expect(page.getByRole('button',{name:'重试摄像机列表'})).toBeVisible(); return state; }
  await expect(page.getByRole('button',{name:'精确导出',exact:true})).toBeEnabled();
  await expect(page.locator('video')).toHaveCount(1);
  return state;
}

test('duplicate clicks create one durable task and reload recovers it',async({page})=>{
  const state=await protocol(page);state.delay=200;
  await page.getByRole('button',{name:'精确导出',exact:true}).evaluate(button=>{(button as HTMLButtonElement).click();(button as HTMLButtonElement).click();});
  await expect(page.getByText('等待处理 · 精确')).toBeVisible();expect(state.submitted).toBe(1);
  await page.reload();await expect(page.getByText('等待处理 · 精确')).toBeVisible();expect(state.submitted).toBe(1);
  await page.getByRole('button',{name:'取消导出',exact:true}).click();await expect(page.getByText('已取消 · 精确')).toBeVisible();expect(state.cancelled).toBe(1);
});

test('camera changes discard stale playback and offer an explicit retry after query failure',async({page})=>{
  const state=await protocol(page);state.timelineDelay=350;state.timelineFailure=true;
  await page.getByRole('checkbox',{name:'two',exact:true}).uncheck();
  await expect(page.locator('video')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'截图',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'精确导出',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'重试时间线'})).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('时间线查询失败');
  state.timelineDelay=0;state.timelineFailure=false;
  await page.getByRole('button',{name:'重试时间线'}).click();
  await expect(page.locator('video')).toHaveCount(1);
  await expect(page.getByRole('button',{name:'精确导出',exact:true})).toBeEnabled();
});

test('an initial camera catalog failure can recover without reloading or resetting an empty selection',async({page})=>{
  const state=await protocol(page,{catalogFailure:true});state.catalogFailure=false;
  await expect(page.getByRole('button',{name:'播放',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'重试摄像机列表'}).click();
  await expect(page.locator('video')).toHaveCount(1);
  for(const camera of ['cam','two','three','four'])await page.getByRole('checkbox',{name:camera,exact:true}).uncheck();
  await page.getByRole('button',{name:'刷新时间线',exact:true}).click();
  await expect(page.getByRole('checkbox',{name:'cam',exact:true})).not.toBeChecked();
  await expect(page.locator('video')).toHaveCount(0);
  await expect(page.getByText('选择 1–4 路摄像机查看归档。')).toBeVisible();
});

test('a late old-day response cannot replace the current day or restart a pending play',async({page})=>{
  await protocol(page);
  await page.evaluate(()=>{(window as unknown as {holdPlayback:boolean}).holdPlayback=true;});
  await page.getByRole('button',{name:'播放',exact:true}).click();
  await expect(page.getByRole('button',{name:'取消等待播放',exact:true})).toBeVisible();
  let resolveOld!:()=>void;const old=new Promise<void>(resolve=>{resolveOld=resolve;});let requested=false;
  const yesterday=new Date(dayStart-86400000).toISOString().slice(0,10);
  await page.route('**/api/v1/nvr/timeline?**',async route=>{
    const from=Number(new URL(route.request().url()).searchParams.get('from'));
    const previous=from===dayStart-86400000;
    if(previous){requested=true;await old;}
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({fromUtcMs:from,toUtcMs:from+86400000,queryDurationMs:2,
      storageTimeZone:'UTC',cameras:[{cameraId:'cam',recordedStream:'main',gaps:[],retentionBoundaryUtcMs:null,
        segments:[{...segment,id:previous?'e'.repeat(32):segment.id,startUtcMs:from+3600000,endUtcMs:from+3630000,
          mediaUrl:'/api/v1/nvr/media/'+(previous?'e'.repeat(32):segment.id)}]}]})}).catch(()=>{});
  });
  await page.getByLabel('UTC 日期').fill(yesterday);await expect.poll(()=>requested).toBe(true);
  await page.getByLabel('UTC 日期').fill(new Date(dayStart).toISOString().slice(0,10));
  await expect(page.locator('video')).toHaveAttribute('src',segment.mediaUrl);
  resolveOld();await page.evaluate(()=>{(window as unknown as {releasePlayback:()=>void}).releasePlayback();});
  await expect(page.getByRole('button',{name:'播放',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'暂停',exact:true})).toHaveCount(0);
  await expect(page.locator('video')).toHaveAttribute('src',segment.mediaUrl);
});

test('a hung timeline query times out and remains retryable',async({page})=>{
  await protocol(page);await page.clock.install();
  let arrived=false;
  await page.route('**/api/v1/nvr/timeline?**',route=>{arrived=true;void route;});
  await page.getByRole('button',{name:'刷新时间线',exact:true}).click();await expect.poll(()=>arrived).toBe(true);
  await page.clock.runFor(12_001);
  await expect(page.getByRole('alert')).toContainText('查询超时');
  await expect(page.getByRole('button',{name:'重试时间线'})).toBeEnabled();
  await expect(page.locator('video')).toHaveCount(0);
  await page.unroute('**/api/v1/nvr/timeline?**');
  await page.getByRole('button',{name:'重试时间线'}).click();await expect(page.locator('video')).toHaveCount(1);
});

test('an unconfirmed snapshot timeout restores controls without an automatic retry',async({page})=>{
  await protocol(page);await page.clock.install();let requests=0;
  await page.route('**/api/v1/nvr/snapshots',route=>{requests++;void route;});
  await page.getByRole('button',{name:'截图',exact:true}).click();await expect.poll(()=>requests).toBe(1);
  await expect(page.getByLabel('UTC 日期')).toBeDisabled();
  await page.clock.runFor(35_001);
  await expect(page.getByText(/操作超时，结果尚未确认/)).toBeVisible();
  await expect(page.getByRole('button',{name:'截图',exact:true})).toBeEnabled();
  await expect(page.getByLabel('UTC 日期')).toBeEnabled();expect(requests).toBe(1);
});

test('delete unloads its media reader and restores the player after a protected-segment rejection',async({page})=>{
  // This fixture tests delete/recovery; its media URLs do not contain real MP4.
  await page.addInitScript(()=>document.addEventListener('error',event=>{
    if(event.target instanceof HTMLMediaElement)event.stopImmediatePropagation();
  },true));
  await protocol(page);page.on('dialog',dialog=>dialog.accept());
  let resolveDelete!:()=>void;const pending=new Promise<void>(resolve=>{resolveDelete=resolve;});let arrived=false;
  await page.route('**/api/v1/nvr/segments/**',async route=>{
    arrived=true;await pending;
    await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:{code:'segment_conflict',message:'protected'}})});
  });
  await page.getByRole('button',{name:'删除',exact:true}).click();await expect.poll(()=>arrived).toBe(true);
  await expect(page.locator('video')).toHaveCount(0);
  await expect(page.getByText('正在释放回放保护…').first()).toBeVisible();
  resolveDelete();
  await expect(page.getByText(/片段已锁定，或仍被回放、导出使用/)).toBeVisible();
  await expect(page.locator('video')).toHaveAttribute('src',segment.mediaUrl);
  await expect(page.getByRole('button',{name:'删除',exact:true})).toBeEnabled();
});

for(const width of [390,1280])test(`timeline ruler, rail and playhead align at ${width}px without label seeks`,async({page})=>{
  await page.setViewportSize({width,height:844});await protocol(page);
  const rail=page.locator('.track-rail').first();const bounds=await rail.boundingBox();expect(bounds).not.toBeNull();
  await rail.click({position:{x:bounds!.width/2,y:5}});
  const seek=page.getByRole('slider',{name:'回放时间游标'});
  await expect.poll(async()=>Math.abs(Number(await seek.inputValue())-(dayStart+43200000))).toBeLessThan(864000);
  const before=await seek.inputValue();await page.locator('.timeline-track > strong').first().click();await expect(seek).toHaveValue(before);
  const alignment=await page.evaluate(()=>{
    const rail=document.querySelector('.track-rail')!.getBoundingClientRect();
    const ruler=document.querySelector('.time-ruler')!.getBoundingClientRect();
    const marker=document.querySelector('.playhead')!.getBoundingClientRect();
    const input=document.querySelector('input[type=range]') as HTMLInputElement;
    const fraction=(Number(input.value)-Number(input.min))/(Number(input.max)-Number(input.min)+1);
    return {left:Math.abs(ruler.left-rail.left),width:Math.abs(ruler.width-rail.width),marker:Math.abs(marker.left-(rail.left+rail.width*fraction))};
  });
  expect(alignment.left).toBeLessThan(1);expect(alignment.width).toBeLessThan(1);expect(alignment.marker).toBeLessThan(1);
});

test('lost submit response is reconciled from history without a second POST',async({page})=>{
  const state=await protocol(page);state.lost=true;
  await page.getByRole('button',{name:'快速导出',exact:true}).click();
  await expect(page.getByText('等待处理 · 快速')).toBeVisible();
  await expect(page.getByRole('button',{name:'恢复同一次提交'})).toHaveCount(0);expect(state.submitted).toBe(1);
});

test('completed result includes effective boundaries, audio evidence and gap warning',async({page})=>{
  const state=await protocol(page);await page.getByRole('button',{name:'快速导出',exact:true}).click();
  await expect(page.getByText('等待处理 · 快速')).toBeVisible();
  state.jobs[0]={...state.jobs[0],state:'completed',result:{exportId:'b'.repeat(32),auditId:'c'.repeat(32),mode:'fast',
    requestedRange:{fromUtcMs:start,toUtcMs:start+10000},effectiveRange:{fromUtcMs:start,toUtcMs:start+30000},manifestSha256:'e'.repeat(64),
    manifestUrl:'/api/v1/nvr/downloads/'+ 'b'.repeat(32)+'/manifest.json',files:[{cameraId:'cam',name:'cam.mp4',sha256:'f'.repeat(64),
      downloadUrl:'/api/v1/nvr/downloads/'+ 'b'.repeat(32)+'/cam.mp4',coverage:{intervals:[],gaps:[{fromUtcMs:start+5000,toUtcMs:start+6000}],overlap:false}}]}};
  await page.reload();await expect(page.getByText('导出完成 · 快速')).toBeVisible();
  await expect(page.getByRole('link',{name:'下载证据清单'})).toBeVisible();await expect(page.getByText(/含 1 处录像断档/)).toBeVisible();
});

test('mobile archive keeps four selected cameras and exposes keyboard seek and downloads',async({page})=>{
  await page.setViewportSize({width:390,height:844});await protocol(page);
  await expect(page.getByRole('checkbox',{name:'five',exact:true})).toBeDisabled();
  const seek=page.getByRole('slider',{name:'回放时间游标'});await seek.focus();await page.keyboard.press('ArrowRight');
  await expect(seek).toHaveValue(String(start+1000));
  await page.getByRole('button',{name:'截图',exact:true}).click();await expect(page.getByRole('link',{name:'下载最近截图'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('a rejected play cannot report playback as running',async({page})=>{
  await protocol(page);await page.evaluate(()=>{(window as unknown as {rejectPlayback:boolean}).rejectPlayback=true;});
  await page.getByRole('button',{name:'播放',exact:true}).click();
  await expect(page.getByText(/回放未能开始/)).toBeVisible();await expect(page.getByRole('button',{name:'播放',exact:true})).toBeVisible();
});

test('deleting a selected segment pauses playback and releases its lease first',async({page})=>{
  const state=await protocol(page);page.on('dialog',dialog=>dialog.accept());
  await expect.poll(()=>state.leases).toBeGreaterThan(0);
  await page.getByRole('button',{name:'删除',exact:true}).click();
  await expect.poll(()=>state.deleted).toBe(1);expect(state.released).toBeGreaterThan(0);
  await expect(page.getByText('片段已删除并写入审计。')).toBeVisible();
});

test('gap playback advances and resumes the next mounted segment',async({page})=>{
  const state=await protocol(page);
  state.segments.push({...segment,id:'e'.repeat(32),startUtcMs:start+60000,endUtcMs:start+90000,
    mediaUrl:'/api/v1/nvr/media/'+ 'e'.repeat(32)});
  // Media transport is a fixture; this test isolates player lifecycle and gap
  // control. Actual H264 decode is covered by the native/emulator media gates.
  await page.addInitScript(()=>document.addEventListener('error',event=>{
    if(event.target instanceof HTMLMediaElement)event.stopImmediatePropagation();
  },true));
  await page.reload();await expect(page.locator('video')).toHaveCount(1);
  await page.getByRole('button',{name:'播放',exact:true}).click();
  await expect(page.getByRole('button',{name:'暂停',exact:true})).toBeVisible();
  await page.locator('video').dispatchEvent('ended');
  await expect(page.locator('video')).toHaveAttribute('src','/api/v1/nvr/media/'+ 'e'.repeat(32));
  await page.locator('video').dispatchEvent('loadedmetadata');
  await expect(page.locator('video')).toHaveAttribute('data-played','true');
  await expect(page.getByText('已跳过录像断档，恢复下一片段。')).toBeVisible();
});

test('export permission denial explains the role and disables submission',async({page})=>{
  const state=await protocol(page);state.denied=true;
  await page.getByRole('button',{name:'刷新任务',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('exporter');
  await expect(page.getByRole('button',{name:'快速导出',exact:true})).toBeDisabled();
});

test('cancelling a pending play prevents its late completion from restarting playback',async({page})=>{
  await protocol(page);await page.evaluate(()=>{(window as unknown as {holdPlayback:boolean}).holdPlayback=true;});
  await page.getByRole('button',{name:'播放',exact:true}).click();
  await page.getByRole('button',{name:'取消等待播放',exact:true}).click();
  await page.evaluate(()=>{(window as unknown as {releasePlayback:()=>void}).releasePlayback();});
  await expect(page.getByRole('button',{name:'播放',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'暂停',exact:true})).toHaveCount(0);
  await expect(page.locator('video')).toHaveAttribute('data-played','false');
});
