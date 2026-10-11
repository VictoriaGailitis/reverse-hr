/** Mount practical controls inside an authenticated candidate page.
 * api(service, path, {method, body, version, key}) must provide authenticated JSON requests.
 * onReady receives the immutable reference for the existing Assessment submit command.
 */
const limit = 32 * 1024 * 1024;
const chunkSize = 262144;
const digest = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
function element(tag, text) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  return node;
}
function controls(root) {
  const section = element('section');
  const status = element('p', 'Готово к работе');
  status.setAttribute('role', 'status');
  section.append(status);
  root.replaceChildren(section);
  return { section, status, button(text, callback) {
    const button = element('button', text);
    button.type = 'button';
    button.addEventListener('click', async () => {
      button.disabled = true;
      let unlock = true;
      try { unlock = (await callback()) !== false; } catch { status.textContent = 'Не удалось выполнить действие. Проверьте доступ и повторите попытку.'; }
      finally { button.disabled = !unlock; }
    });
    section.append(button);
    return button;
  }};
}

export function mountRecording(root, {api, sessionId, stageId, recordingConsentId, video = false, onReady, proctor}) {
  const ui = controls(root);
  let ownedProctor = false, proctorPromise;
  async function ensureProctor() {
    if (!proctor) {
      proctorPromise ??= mountProctoring({api, sessionId, stageId, onStatus: state => {
        if (state.status === 'delivery_retry' || state.status === 'buffer_full') ui.status.textContent = 'Журнал событий ожидает доставки. Проверьте соединение.';
      }}).catch(error => { proctorPromise = undefined; throw error; });
      proctor = await proctorPromise;
      ownedProctor = true;
      if (disposed) { await proctor.dispose(); throw new Error('Disposed'); }
    }
  }
  const preview = element(video ? 'video' : 'audio');
  preview.controls = true;
  preview.muted = true;
  preview.setAttribute('aria-label', 'Предпросмотр записи');
  ui.section.append(preview);
  let recorder, stream, blob, row, started, duration, manifest, timer, objectUrl, restartVersion, disposed = false, restartPending = false, saving = false;
  let createKey = crypto.randomUUID();
  function release() {
    clearTimeout(timer);
    stream?.getTracks().forEach(track => track.stop());
    preview.srcObject = null;
  }
  const start = ui.button('Начать запись', async () => {
    if (disposed || saving || recorder?.state === 'recording' || blob) return false;
    await ensureProctor();
    if (!navigator.mediaDevices || !globalThis.MediaRecorder) throw new Error('Capture unavailable');
    await api('media', '/v1/recordings/admission', {method:'POST', body:{session_id:sessionId, stage_id:stageId, recording_consent_id:recordingConsentId}});
    if (disposed) return;
    const mime = (video ? ['video/webm;codecs=vp8,opus','video/webm','video/mp4'] : ['audio/webm;codecs=opus','audio/webm','audio/ogg']).find(type => MediaRecorder.isTypeSupported(type));
    if (!mime) throw new Error('Recording format unavailable');
    stream = await navigator.mediaDevices.getUserMedia({
      audio:{channelCount:{ideal:1,max:2},sampleRate:{ideal:48000,max:48000}},
      video:video ? {width:{ideal:1280,max:1920},height:{ideal:720,max:1080},frameRate:{ideal:30,max:60}} : false
    }).catch(error => { proctor?.record('recording_error'); throw error; });
    if (disposed) { release(); return; }
    stream.getTracks().forEach(track => track.addEventListener?.('ended', () => {
      proctor?.record('recording_error');
      if (recorder?.state === 'recording') recorder.stop();
    }));
    try {
      recorder = new MediaRecorder(stream, {mimeType:mime});
      const parts = [];
      let size = 0;
      recorder.addEventListener('dataavailable', event => {
        size += event.data.size;
        if (size > limit) {
          parts.length = 0;
          if (recorder.state === 'recording') recorder.stop();
          ui.status.textContent = 'Запись превысила допустимый размер. Начните заново.';
        } else if (size <= limit) parts.push(event.data);
      });
      recorder.addEventListener('stop', () => {
        proctor?.record('recording_stopped');
        duration = Math.min(7200000, Math.max(1, Math.round(performance.now()-started)));
        release();
        if (disposed) return;
        if (size <= limit && size > 0) {
          blob = new Blob(parts, {type:mime.split(';')[0]});
          objectUrl = URL.createObjectURL(blob);
          preview.src = objectUrl;
          preview.muted = false;
          ui.status.textContent = 'Запись готова. Просмотрите её перед отправкой.';
          upload.disabled = false;
        }
        stop.disabled = true;
        start.disabled = Boolean(blob);
      });
      recorder.addEventListener('error', () => { proctor?.record('recording_error'); release(); ui.status.textContent = 'Запись прервана. Доступный файл можно отправить повторно.'; });
      started = performance.now();
      recorder.start(1000);
      proctor?.record('recording_started');
      timer = setTimeout(() => { if (recorder.state === 'recording') recorder.stop(); }, 7200000);
      start.disabled = true;
      stop.disabled = false;
      preview.srcObject = stream;
      if (video) preview.play().catch(() => {});
      ui.status.textContent = 'Идёт запись';
      return false;
    } catch (error) { release(); throw error; }
  });
  const stop = ui.button('Остановить запись', () => { if (recorder?.state === 'recording') recorder.stop(); });
  stop.disabled = true;
  const upload = ui.button('Сохранить запись', async () => {
    if (disposed || saving || !blob || blob.size > limit || blob.size === 0) return;
    saving = true;
    try {
    const bytes = await blob.arrayBuffer();
    if (!manifest) manifest = {session_id:sessionId, stage_id:stageId, recording_consent_id:recordingConsentId, mime:blob.type, size:blob.size, digest:await digest(bytes), client_duration_ms:duration};
    if (!row) row = await api('media', '/v1/recordings', {method:'POST', key:createKey, body:manifest});
    row = await api('media', `/v1/recordings/${row.recording_id}`, {});
    if (restartPending) {
      if (restartVersion === undefined) restartVersion = row.version;
      row = await api('media', `/v1/recordings/${row.recording_id}/restart`, {method:'POST', key:`${createKey}-restart`, version:restartVersion, body:manifest});
      restartPending = false;
    }
    const received = new Set(row.received_chunks);
    for (let start = 0, number = 0; start < bytes.byteLength; start += chunkSize, number++) {
      if (disposed) return;
      if (received.has(number)) continue;
      const part = new Uint8Array(bytes.slice(start, start+chunkSize));
      let binary = '';
      for (const byte of part) binary += String.fromCharCode(byte);
      row = await api('media', `/v1/recordings/${row.recording_id}/chunks/${number}`, {method:'PUT', version:row.version,
        key:`${createKey}-part-${number}`, body:{data_base64:btoa(binary), digest:await digest(part)}});
      ui.status.textContent = `Сохранено частей: ${row.received_chunks.length}`;
    }
    if (row.status !== 'finalized') row = await api('media', `/v1/recordings/${row.recording_id}/finalize`, {method:'POST', key:`${createKey}-finalize`, version:row.version});
    if (proctor && !await proctor.flush()) throw new Error('Telemetry delivery pending');
    await onReady({workspace_id:row.recording_id, snapshot_id:row.snapshot_id});
    ui.status.textContent = 'Запись сохранена';
    return false;
    } finally { saving = false; }
  });
  upload.disabled = true;
  ui.button('Записать заново', async () => {
    if (saving || recorder?.state === 'recording') return;
    if (manifest) {
      if (!row) row = await api('media', '/v1/recordings', {method:'POST', key:createKey, body:manifest});
      row = await api('media', `/v1/recordings/${row.recording_id}`, {});
      if (row.status === 'finalized') { ui.status.textContent = 'Сохранённый снимок нельзя заменить.'; return; }
      restartPending = true;
    }
    manifest = undefined;
    restartVersion = undefined;
    createKey = crypto.randomUUID();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = undefined;
    blob = undefined;
    preview.removeAttribute('src');
    preview.muted = true;
    start.disabled = false;
    upload.disabled = true;
    ui.status.textContent = 'Готово к новой записи';
  });
  return () => { disposed = true; if (recorder?.state === 'recording') recorder.stop(); release(); if (objectUrl) URL.revokeObjectURL(objectUrl); root.replaceChildren(); if (ownedProctor) return proctor.dispose(); };
}

export async function mountBoard(root, {api, sessionId, stageId, boardId, onReady, proctor}) {
  const ui = controls(root);
  const canvas = element('canvas');
  canvas.width = 1000;
  canvas.height = 600;
  canvas.style.cssText = 'max-width:100%;border:1px solid #777;touch-action:none';
  canvas.tabIndex = 0;
  canvas.setAttribute('aria-label', 'Доска для рисования. Для текстовых объектов используйте поле ниже.');
  ui.section.append(canvas);
  const input = element('textarea');
  input.maxLength = 2000;
  input.setAttribute('aria-label', 'Текст на доске');
  ui.section.append(input);
  let row = boardId ? await api('whiteboard', `/v1/boards/${boardId}`, {}) : await api('whiteboard', '/v1/boards', {method:'POST', key:crypto.randomUUID(), body:{session_id:sessionId, stage_id:stageId}});
  const ownedProctor = !proctor && row.status === 'editing';
  if (ownedProctor) proctor = await mountProctoring({api, sessionId, stageId, onStatus: state => {
    if (state.status === 'delivery_retry' || state.status === 'buffer_full') ui.status.textContent = 'Журнал событий ожидает доставки. Проверьте соединение.';
  }});
  const path = `/v1/boards/${row.board_id}`;
  let queue = Promise.resolve(), drawing, disposed = false, failed = false, frozen = row.status === 'sealed';
  const ctx = canvas.getContext('2d');
  function draw() {
    ctx.clearRect(0,0,canvas.width,canvas.height);
    for (const shape of [...row.state, ...(drawing ? [drawing] : [])]) {
      ctx.strokeStyle = shape.color || '#000000';
      ctx.fillStyle = shape.color || '#000000';
      ctx.lineWidth = shape.width || 2;
      const first = shape.points[0], last = shape.points[shape.points.length-1];
      ctx.beginPath();
      if (shape.kind === 'text') { ctx.font='18px sans-serif'; ctx.fillText(shape.text,first.x,first.y); }
      else if (shape.kind === 'rectangle') ctx.strokeRect(first.x, first.y, last.x-first.x, last.y-first.y);
      else if (shape.kind === 'ellipse') { ctx.ellipse((first.x+last.x)/2,(first.y+last.y)/2,Math.abs(last.x-first.x)/2,Math.abs(last.y-first.y)/2,0,0,Math.PI*2); ctx.stroke(); }
      else { ctx.moveTo(first.x,first.y); for (const point of shape.points) ctx.lineTo(point.x,point.y); ctx.stroke(); }
    }
  }
  function operation(body) {
    queue = queue.then(async () => {
      if (disposed || frozen) return;
      try {
        row = await api('whiteboard', path+'/operations', {method:'POST', key:body.operation_id, version:row.version, body});
        failed = false;
        ui.status.textContent = 'Изменения сохранены';
      } catch {
        failed = true;
        row = await api('whiteboard', path, {});
        ui.status.textContent = 'Изменение не сохранено. Повторите его.';
      }
      frozen = row.status === 'sealed';
      draw();
    }).catch(() => { failed = true; ui.status.textContent = 'Нет доступа к доске. Обновите страницу.'; });
    return queue;
  }
  function point(event) { const bounds=canvas.getBoundingClientRect(); return {x:Math.max(0,Math.min(1000,(event.clientX-bounds.left)*1000/bounds.width)), y:Math.max(0,Math.min(600,(event.clientY-bounds.top)*600/bounds.height))}; }
  canvas.onpointerdown = event => { if (frozen || disposed || drawing) return; canvas.setPointerCapture(event.pointerId); drawing={id:crypto.randomUUID(), kind:'stroke', points:[point(event)], color:'#000000', width:2}; };
  canvas.onpointermove = event => { if (drawing && drawing.points.length<500) { drawing.points.push(point(event)); draw(); }};
  canvas.onpointerup = () => { if (!drawing) return; const shape=drawing; drawing=null; operation({operation_id:crypto.randomUUID(), action:'put', object_id:shape.id, shape}); };
  canvas.onpointercancel = () => { drawing=null; draw(); };
  ui.button('Добавить текст', async () => { if (frozen || !input.value.trim()) return; const shape={id:crypto.randomUUID(), kind:'text', points:[{x:30,y:40}], text:input.value}; await operation({operation_id:crypto.randomUUID(), action:'put', object_id:shape.id, shape}); });
  ui.button('Удалить последний объект', async () => { await queue; if (frozen || !row.state.length) return; await operation({operation_id:crypto.randomUUID(), action:'delete', object_id:row.state[row.state.length-1].id}); });
  ui.button('Завершить доску', async () => {
    await queue;
    if (failed || drawing) throw new Error('Unsaved operation');
    if (!frozen) row = await api('whiteboard', path+'/seal', {method:'POST', key:crypto.randomUUID(), version:row.version});
    frozen=true; draw();
    if (proctor && !await proctor.flush()) throw new Error('Telemetry delivery pending');
    await onReady({workspace_id:row.board_id, snapshot_id:row.snapshot_id});
    ui.status.textContent='Доска сохранена';
  });
  draw();
  return () => { disposed=true; root.replaceChildren(); if (ownedProctor) return proctor.dispose(); };
}

/** One admitted telemetry stream per mounted stage. No clipboard content, URLs or key logging.
 * Technical delivery failures are reported through onStatus; retry preserves event IDs and sequence.
 * Mount once at the stage controller, then pass the returned object as `proctor` to recording controls.
 */
export async function mountProctoring({api, sessionId, stageId, onStatus = () => {},
  documentTarget = document, windowTarget = globalThis, heartbeatMs = 30000}) {
  const startedAt = new Date().toISOString(), started = performance.now(), streamId = crypto.randomUUID();
  const create = {method:'POST', key:streamId,
    body:{session_id:sessionId, stage_id:stageId, stream_id:streamId, client_started_at:startedAt}};
  for (let attempt=0; ; attempt++) {
    try { await api('proctoring', '/v1/proctoring/streams', create); break; }
    catch (error) { if (attempt >= 2) throw error; }
  }
  const path = `/v1/proctoring/streams/${streamId}/events`;
  let sequence = 0, queue = [], pending, active, timer, disposed = false, overflow = false;
  const listeners = [];
  const kinds = new Set(['heartbeat','visibility_hidden','visibility_visible','focus_lost','focus_gained',
    'paste','recording_started','recording_stopped','recording_error','offline','online','telemetry_overflow']);
  function record(kind) {
    if (disposed || !kinds.has(kind)) return;
    if (sequence >= 20000) { onStatus({status:'capacity_reached'}); return; }
    const event = {event_id:crypto.randomUUID(), sequence:++sequence, kind,
      client_time:new Date().toISOString(), elapsed_ms:Math.min(86400000, Math.max(0,Math.round(performance.now()-started)))};
    if (queue.length >= 500) { overflow = true; onStatus({status:'buffer_full'}); return; }
    queue.push(event);
  }
  async function flush() {
    if (active) return active;
    active = Promise.resolve().then(async () => {
      try {
        while (queue.length || pending) {
          if (!pending) pending = {key:crypto.randomUUID(), events:queue.splice(0,50)};
          await api('proctoring',path,{method:'POST',key:pending.key,body:{events:pending.events}});
          pending = undefined;
          if (overflow && queue.length < 500) { overflow = false; record('telemetry_overflow'); }
        }
        onStatus({status:'saved'});
        return true;
      } catch { onStatus({status:'delivery_retry'}); return false; }
      finally { active = undefined; }
    });
    return active;
  }
  function listen(target, name, handler) {
    target.addEventListener(name,handler);
    listeners.push(() => target.removeEventListener(name,handler));
  }
  listen(documentTarget,'visibilitychange',() => record(documentTarget.hidden ? 'visibility_hidden' : 'visibility_visible'));
  listen(windowTarget,'blur',() => record('focus_lost'));
  listen(windowTarget,'focus',() => record('focus_gained'));
  listen(documentTarget,'paste',() => record('paste'));
  listen(windowTarget,'offline',() => record('offline'));
  listen(windowTarget,'online',() => { record('online'); void flush(); });
  record('heartbeat');
  record(documentTarget.hidden ? 'visibility_hidden' : 'visibility_visible');
  await flush();
  function schedule() {
    timer = setTimeout(async () => { if (disposed) return; record('heartbeat'); await flush(); if (!disposed) schedule(); }, heartbeatMs);
  }
  schedule();
  return {streamId, record, flush, async dispose() {
    disposed = true; clearTimeout(timer); listeners.forEach(remove => remove());
    return flush();
  }};
}
