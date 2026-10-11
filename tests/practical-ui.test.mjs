import {test} from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {mountBoard, mountRecording} from '../src/reverse_hr/shared/assets/practical.mjs';

Object.defineProperty(globalThis,'crypto',{configurable:true,value:webcrypto});
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.handlers={}; this.value=''; this.style={}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  setAttribute() {}
  removeAttribute() {}
  play() { return Promise.resolve(); }
  addEventListener(event, handler) { this.handlers[event]=handler; }
  async click() { if (!this.disabled) await this.handlers.click(); }
  getBoundingClientRect() { return {left:0,top:0,width:1000,height:600}; }
  setPointerCapture() {}
  getContext() { return new Proxy({}, {get:()=>()=>{}}); }
}
globalThis.document = {createElement:tag=>new Element(tag), addEventListener(){}, removeEventListener(){}, hidden:false};
globalThis.addEventListener=()=>{};
globalThis.removeEventListener=()=>{};
function button(root,text) { return root.children[0].children.find(n=>n.tag==='button' && n.textContent===text); }

test('board serializes writes, restores server state after a failed write and blocks seal', async () => {
  const root=new Element('root');
  let row={board_id:'board',version:1,status:'editing',state:[]}, fail=false;
  const calls=[], ready=[];
  const api=async (service,path,command) => {
    if (service === 'proctoring') return {};
    calls.push([service,path,command]);
    if (command.method==='POST' && path.endsWith('/operations')) {
      assert.equal(command.version,row.version);
      if (fail) throw new Error('unavailable');
      row={...row,version:row.version+1,state:[command.body.shape]};
    } else if (path.endsWith('/seal')) row={...row,status:'sealed',snapshot_id:'snap'};
    return structuredClone(row);
  };
  const dispose=await mountBoard(root,{api,sessionId:'session',stageId:'stage',onReady:value=>ready.push(value)});
  const input=root.children[0].children.find(n=>n.tag==='textarea');
  input.value='<script>synthetic</script>';
  await button(root,'Добавить текст').click();
  assert.equal(row.state[0].text,input.value);
  fail=true;
  await button(root,'Добавить текст').click();
  await button(root,'Завершить доску').click();
  assert.equal(calls.filter(c=>c[1].endsWith('/seal')).length,0);
  assert.equal(ready.length,0);
  fail=false;
  await button(root,'Добавить текст').click();
  await button(root,'Завершить доску').click();
  assert.deepEqual(ready,[{workspace_id:'board',snapshot_id:'snap'}]);
  assert.equal(row.status,'sealed');
  dispose();
  assert.equal(root.children.length,0);
});

test('recording checks server permission before opening a device and retries a stable manifest', async () => {
  const root=new Element('root');
  const calls=[], manifests=[];
  let recorder, stopped=0, permission=false, uploadFailed=false;
  const stream={getTracks:()=>[{stop:()=>stopped++}]};
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async constraints=>{
    assert.equal(permission,true);
    assert.equal(constraints.audio.sampleRate.max,48000);
    assert.equal(constraints.audio.channelCount.max,2);
    assert.equal(constraints.video,false);
    return stream;
  }}}});
  class Recorder {
    static isTypeSupported() { return true; }
    constructor() { recorder=this; this.state='inactive'; this.handlers={}; }
    addEventListener(event,handler) { this.handlers[event]=handler; }
    start() { this.state='recording'; }
    stop() {
      this.state='inactive';
      this.handlers.dataavailable({data:new Blob([new Uint8Array([0x1a,0x45,0xdf,0xa3,1])])});
      this.handlers.stop();
    }
  }
  globalThis.MediaRecorder=Recorder;
  let row;
  const api=async (service,path,command) => {
    if (service === 'proctoring') return {};
    calls.push(path);
    if (path.endsWith('/admission')) { permission=true; return {allowed:true}; }
    if (path==='/v1/recordings') {
      manifests.push(command.body);
      if (!uploadFailed) { uploadFailed=true; throw new Error('lost response'); }
      row={recording_id:'recording',version:1,received_chunks:[],status:'uploading'};
    } else if (path.endsWith('/chunks/0')) row={...row,version:2,received_chunks:[0]};
    else if (path.endsWith('/finalize')) row={...row,version:3,status:'finalized',snapshot_id:'snap'};
    return structuredClone(row);
  };
  const ready=[];
  const dispose=mountRecording(root,{api,sessionId:'session',stageId:'stage',recordingConsentId:'consent',onReady:value=>ready.push(value)});
  await button(root,'Начать запись').click();
  assert.equal(recorder.state,'recording');
  assert.equal(button(root,'Начать запись').disabled,true);
  await button(root,'Остановить запись').click();
  assert.equal(stopped,1);
  await button(root,'Сохранить запись').click();
  await button(root,'Сохранить запись').click();
  assert.deepEqual(manifests[0],manifests[1]);
  assert.deepEqual(ready,[{workspace_id:'recording',snapshot_id:'snap'}]);
  assert.equal(calls[0],'/v1/recordings/admission');
  dispose();
});

test('recording replaces an invalid upload and recovers a lost restart response', async () => {
  const root=new Element('root');
  let row, recorder, capture=0, lostRestart=false, restartRequest;
  const ready=[], stream={getTracks:()=>[{stop(){}}]};
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async constraints=>{
    assert.equal(constraints.video.width.max,1920);
    assert.equal(constraints.video.height.max,1080);
    assert.equal(constraints.video.frameRate.max,60);
    return stream;
  }}}});
  class Recorder {
    static isTypeSupported() { return true; }
    constructor() { recorder=this; this.state='inactive'; this.handlers={}; capture++; }
    addEventListener(event,handler) { this.handlers[event]=handler; }
    start() { this.state='recording'; }
    stop() {
      this.state='inactive';
      this.handlers.dataavailable({data:new Blob([new Uint8Array([0x1a,0x45,0xdf,0xa3,capture])])});
      this.handlers.stop();
    }
  }
  globalThis.MediaRecorder=Recorder;
  const api=async (service,path,command) => {
    if (service === 'proctoring') return {};
    if (path.endsWith('/admission')) return {allowed:true};
    if (path==='/v1/recordings') row={recording_id:'recording',version:1,status:'uploading',received_chunks:[]};
    else if (path.endsWith('/restart')) {
      if (!lostRestart) {
        restartRequest=structuredClone(command);
        assert.equal(command.version,2);
        row={...row,version:3,received_chunks:[]};
        lostRestart=true;
        throw new Error('response lost after commit');
      }
      assert.deepEqual(command,restartRequest);
    } else if (path.endsWith('/chunks/0')) {
      assert.equal(command.version,row.version);
      row={...row,version:row.version+1,received_chunks:[0]};
    } else if (path.endsWith('/finalize')) {
      if (capture===1) throw new Error('invalid media');
      row={...row,version:row.version+1,status:'finalized',snapshot_id:'snapshot'};
    }
    return structuredClone(row);
  };
  const dispose=mountRecording(root,{api,sessionId:'session',stageId:'stage',recordingConsentId:'consent',video:true,onReady:ref=>ready.push(ref)});
  await button(root,'Начать запись').click();
  await button(root,'Остановить запись').click();
  await button(root,'Сохранить запись').click();
  assert.equal(row.status,'uploading');
  await button(root,'Записать заново').click();
  await button(root,'Начать запись').click();
  assert.equal(recorder.state,'recording');
  await button(root,'Остановить запись').click();
  await button(root,'Сохранить запись').click();
  assert.equal(row.version,3);
  await button(root,'Сохранить запись').click();
  assert.deepEqual(ready,[{workspace_id:'recording',snapshot_id:'snapshot'}]);
  assert.equal(row.version,5);
  await button(root,'Записать заново').click();
  assert.equal(capture,2);
  dispose();
});

test('proctoring retries the identical batch, supports later flushes and never reads clipboard data', async () => {
  const {mountProctoring}=await import('../src/reverse_hr/shared/assets/practical.mjs');
  class Target {
    constructor() { this.listeners=new Map(); this.hidden=false; }
    addEventListener(name,handler) { this.listeners.set(name,handler); }
    removeEventListener(name,handler) { if (this.listeners.get(name)===handler) this.listeners.delete(name); }
    emit(name,event={}) { this.listeners.get(name)?.(event); }
  }
  const doc=new Target(), win=new Target(), calls=[], statuses=[];
  let failed=false;
  const proctor=await mountProctoring({api:async (service,path,command)=>{
    assert.equal(service,'proctoring');
    if (path.endsWith('/events')) {
      calls.push(structuredClone(command));
      if (!failed) { failed=true; throw new Error('lost response'); }
    }
    return {};
  },sessionId:'session',stageId:'stage',documentTarget:doc,windowTarget:win,onStatus:s=>statuses.push(s.status),heartbeatMs:3600000});
  doc.emit('paste',{get clipboardData() { throw new Error('Must not read clipboard'); }});
  assert.equal(await proctor.flush(),true);
  assert.deepEqual(calls[0],calls[1]);
  await proctor.flush(); // empty flush must not leave a permanently resolved active promise
  win.emit('blur');doc.hidden=true;doc.emit('visibilitychange');
  await proctor.flush();
  proctor.record('recording_error');await proctor.flush();
  const accepted=calls.slice(1).flatMap(c=>c.body.events);
  assert.deepEqual(accepted.map(e=>e.kind),['heartbeat','visibility_visible','paste','focus_lost','visibility_hidden','recording_error']);
  assert.deepEqual(accepted.map(e=>e.sequence),[1,2,3,4,5,6]);
  assert.deepEqual(Object.keys(accepted[2]).sort(),['client_time','elapsed_ms','event_id','kind','sequence']);
  assert.equal(await proctor.dispose(),true);
  assert.equal(doc.listeners.size,0);assert.equal(win.listeners.size,0);
  assert.ok(statuses.includes('delivery_retry'));
});

test('proctoring buffers are bounded and overflow leaves explicit sequence gaps and a technical marker', async () => {
  const {mountProctoring}=await import('../src/reverse_hr/shared/assets/practical.mjs');
  const target={addEventListener(){},removeEventListener(){},hidden:false};
  let offline=true;const delivered=[];
  const proctor=await mountProctoring({api:async (_,path,cmd)=>{
    if (path.endsWith('/events')) {
      if (offline) throw new Error('offline');
      delivered.push(...cmd.body.events);
    }
  },sessionId:'session',stageId:'stage',documentTarget:target,windowTarget:target,heartbeatMs:3600000});
  for (let i=0;i<700;i++) proctor.record('paste');
  offline=false;assert.equal(await proctor.flush(),true);
  assert.equal(delivered.length,503); // 2 pending + 500 buffered + overflow marker
  assert.equal(delivered.at(-1).kind,'telemetry_overflow');
  assert.equal(delivered.at(-1).sequence,703);
  await proctor.dispose();
});

test('automatic board proctoring blocks onReady until telemetry delivery recovers', async () => {
  const root=new Element('root'), ready=[];
  let row={board_id:'board',version:1,status:'editing',state:[]}, failed=true;
  const creations=[];
  const dispose=await mountBoard(root,{api:async (service,path,cmd)=>{
    if (service==='proctoring') {
      if (path.endsWith('/streams')) {
        creations.push(structuredClone(cmd));
        if (creations.length===1) throw new Error('lost create response');
      } else if (failed) throw new Error('telemetry outage');
      return {};
    }
    if (path.endsWith('/seal')) row={...row,status:'sealed',version:2,snapshot_id:'snapshot'};
    return structuredClone(row);
  },sessionId:'session',stageId:'stage',onReady:result=>ready.push(result)});
  assert.deepEqual(creations[0],creations[1]);
  await button(root,'Завершить доску').click();
  assert.equal(ready.length,0);
  assert.equal(row.status,'sealed');
  failed=false;
  await button(root,'Завершить доску').click();
  assert.deepEqual(ready,[{workspace_id:'board',snapshot_id:'snapshot'}]);
  await dispose();
});
