// Real product HTTP/SOAP and rendered UI; the camera is an isolated synthetic fixture.
const { createRequire }=require('node:module');
const { expect }=createRequire(require('node:path').resolve(__dirname,'../web/package.json'))('@playwright/test');
exports.exerciseDeviceControls=async(page,base,microphone=false)=>{
  await page.goto(base+'/#devices');
  await page.evaluate(async()=>{
    const request=async(path,body)=>{
      const response=await fetch('/api/v1'+path,{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!response.ok)throw new Error('Synthetic device setup failed ('+response.status+')');
      return response.json();
    };
    await request('/cameras',{id:'controlled-live-fixture',name:'Controlled SOAP fixture',adapter:'onvif',
      address:'http://127.0.0.1:19091',profiles:[],username:'test-operator',password:'fixture-password'});
    await request('/cameras/controlled-live-fixture/onvif/sync',{});
    const invalid=await fetch('/api/v1/cameras/controlled-live-fixture/onvif/ptz',{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({operation:'continuous',x:.2,y:0,durationMs:0})});
    if(invalid.status!==400)throw new Error('Invalid movement was not rejected');
  });
  await page.reload();
  await page.getByRole('button',{name:'添加 / ONVIF 发现',exact:true}).click();
  const card=page.locator('.camera-card').filter({has:page.getByRole('heading',{name:'Controlled SOAP fixture',exact:true})});
  const controls=card.locator('.device-controls');
  await controls.getByRole('button',{name:'云台上移'}).click();
  await expect(controls).toContainText('PTZ 命令已确认');
  await controls.getByRole('button',{name:'停止云台'}).click();
  await expect(controls).toContainText('停止云台命令已确认');
  await controls.getByRole('button',{name:'预置位',exact:true}).click();
  await expect(controls.getByRole('button',{name:'Entrance',exact:true})).toBeVisible();
  await controls.getByRole('button',{name:'保存当前位置',exact:true}).click();
  await expect(controls.getByRole('button',{name:'Preset 2',exact:true})).toBeVisible();
  await controls.getByRole('button',{name:'快照',exact:true}).click();
  await expect.poll(()=>controls.locator('img').evaluate(image=>image.naturalWidth)).toBe(160);
  await controls.getByRole('button',{name:'拉取事件',exact:true}).click();
  await expect(controls).toContainText('收到 1 个设备事件');
  if(microphone){
    await controls.getByRole('button',{name:'录制对讲',exact:true}).click();
    await expect(controls).toContainText('正在录音');
    await page.getByRole('button',{name:'返回 Studio',exact:true}).click();
    await expect.poll(()=>page.evaluate(()=>window.deviceStreams.flatMap(stream=>stream.getTracks()).every(track=>track.readyState==='ended'))).toBe(true);
  }
  console.log('Authenticated product: synthetic SOAP PTZ/stop/presets/events, actual FFmpeg JPEG decoding'+(microphone?' and real Chromium virtual-microphone cleanup':'')+' passed; physical camera/audio qualification remains separate');
};
