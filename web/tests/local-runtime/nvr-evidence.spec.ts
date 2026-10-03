import { expect, test, type Page } from '@playwright/test';
import type { NvrExportJob, NvrSegment } from '../../src/types';

const fixture = '/tests/harness/nvr-evidence.html';
const dayStart = Date.parse(`${new Date().toISOString().slice(0,10)}T00:00:00Z`);
const start = dayStart + 3600_000;
const segment: NvrSegment = { id: 'a'.repeat(32), cameraId: 'cam', startUtcMs: start, endUtcMs: start+30000,
  durationMs: 30000, kind:'continuous', videoCodec:'h264', audioCodec:'aac', sizeBytes:1024, integrity:'ok', locked:false,
  mediaUrl:'/api/v1/nvr/media/'+ 'a'.repeat(32) };

async function protocol(page: Page) {
  const state = { jobs: [] as NvrExportJob[], submitted: 0, cancelled: 0, lost: false, delay: 0, denied:false,
    segments: [structuredClone(segment)], leases:0, released:0, deleted:0 };
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
    if(path==='/api/v1/nvr/status') return reply({status:'ok',freeBytes:1e9,diskPressure:false,
      cameras:['cam','two','three','four','five'].map(id=>({id,policy:'continuous',state:'idle',segments:1,eventActive:false}))});
    if(path==='/api/v1/nvr/timeline') return reply({fromUtcMs:dayStart,toUtcMs:dayStart+86400000,storageTimeZone:'UTC',queryDurationMs:2,
      cameras:url.searchParams.getAll('cameraId').map(cameraId=>({cameraId,recordedStream:'main',retentionBoundaryUtcMs:null,
        segments:cameraId==='cam'?state.segments:[],gaps:[]}))});
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
