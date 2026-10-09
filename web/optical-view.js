"use strict";
// Local canvas renderer. Geometry is symbolic; tracing remains server validated.
window.OpticalView = class {
  constructor(root, hooks) {
    this.hooks = hooks; this.scene = null; this.trace = null; this.selected = null;
    this.mode = "3d"; this.rotation = -0.55; this.tilt = 0.42; this.zoom = 1;
    this.history = []; this.sequence = 0; this.aiConfigured = false;
    const make = (tag, cls, text) => { const n = document.createElement(tag); n.className = cls || ""; if (text !== undefined) n.textContent = text; return n; };
    this.make = make;
    const btn = (text, action) => { const n = make("button", "button button-secondary button-small", text); n.type = "button"; n.onclick = action; return n; };
    this.left = make("section", "optics-canvas-panel panel");
    const head = make("div", "optics-toolbar"); head.append(make("h2", "", "光路与镜片"));
    this.modeButton = btn("展开 2D", () => { this.mode = this.mode === "3d" ? "2d" : "3d"; this.modeButton.textContent = this.mode === "3d" ? "展开 2D" : "折转 3D"; this.draw(); });
    head.append(this.modeButton, btn("适配视图", () => { this.zoom = 1; this.rotation = -0.55; this.tilt = 0.42; this.draw(); }));
    this.canvas = make("canvas", "optics-canvas"); this.canvas.tabIndex = 0; this.canvas.setAttribute("aria-label", "光路示意，拖动旋转，滚轮缩放；下方选择镜片编辑参数");
    this.summary = make("p", "optics-summary"); this.warning = make("div", "optics-warnings");
    const note = make("p", "optics-caption", "薄透镜近轴光扇 · 展开轴 z（mm） · 3D 棱镜仅理想折转 · 达屏条数不代表光学效率。拖动旋转，滚轮缩放。");
    this.left.append(head, this.canvas, this.summary, note, this.warning);
    this.right = make("section", "optics-inspector panel"); this.right.append(make("h2", "", "元件参数"));
    this.selector = make("select"); this.selector.setAttribute("aria-label", "选择光学元件"); this.selector.onchange = () => { this.selected = this.selector.value; this.fields(); this.draw(); };
    this.editor = make("div", "optics-fields"); this.right.append(this.selector, this.editor);
    const editActions = make("div", "optics-edit-actions"); this.addKind=make("select"); this.addKind.setAttribute("aria-label","添加元件类型");
    [["lens","薄透镜"],["flyeye","复眼阵列"],["prism","理想棱镜"],["aperture","孔径光阑"]].forEach(([key,text])=>{const n=make("option","",text);n.value=key;this.addKind.append(n);});
    this.addButton=btn("插入元件",()=>this.add()); this.removeButton=btn("移除选中元件",()=>this.remove()); editActions.append(this.addKind,this.addButton,this.removeButton);this.right.append(editActions);
    this.right.append(make("p", "optics-caption", "孔径是子午面全高；宽度仅为符号厚度。光路与标量预算分别编辑，保存原型时一起保存。"));
    const rayBox = make("div", "optics-ray-box"); rayBox.append(make("h3", "", "代表光扇"));
    this.rayInputs = {};
    [["half_angle_deg", "光扇半角 °", 0, 15], ["rays_per_point", "每点光线数", 1, 21], ["source_points", "光源采样点", 1, 9]].forEach(([key, label, min, max]) => {
      const wrap = make("label", "optics-field", label); const input = make("input"); input.type = "number"; input.min = min; input.max = max; input.step = key === "half_angle_deg" ? "0.1" : "1";
      input.oninput = () => { if (!this.scene || this.loading) return; this.scene.rays[key] = input.value === "" ? null : Number(input.value); this.changed(); }; wrap.append(input); rayBox.append(wrap); this.rayInputs[key] = input;
    }); this.right.append(rayBox);
    this.chat = make("section", "optics-chat panel");
    this.chat.append(make("h2", "", "AI 设计助理")); this.status = make("p", "optics-caption", "读取 AI 连接状态…");
    this.chat.append(this.status, make("p", "optics-caption", "内置聊天发送当前原型参数、光路和本面板对话到 OpenAI。修改成功后保存一个新版本；原始资料不随请求发送。"));
    this.messages = make("div", "optics-messages"); this.messages.setAttribute("role", "log"); this.messages.setAttribute("aria-live", "polite");
    this.prompt = make("textarea"); this.prompt.rows = 3; this.prompt.maxLength = 6000; this.prompt.placeholder = "例如：将准直透镜焦距改为 20 mm，检查代表光线是否被孔径截断。"; this.prompt.setAttribute("aria-label", "AI 设计指令");
    this.send = btn("发送给内置 AI", () => this.ask()); this.copy = btn("复制给 Codex / MCP", () => this.copyPrompt());
    const actions = make("div", "optics-chat-actions"); actions.append(this.send, this.copy); this.chat.append(this.messages, this.prompt, actions);
    root.replaceChildren(this.left, this.right, this.chat);
    let drag = null;
    let origin;
    this.canvas.onpointerdown = e => { drag = {x:e.clientX,y:e.clientY}; origin={...drag}; this.canvas.setPointerCapture(e.pointerId); };
    this.canvas.onpointermove = e => { if (!drag || this.mode !== "3d") return; this.rotation += (e.clientX-drag.x)*0.008; this.tilt = Math.max(-1.2,Math.min(1.2,this.tilt+(e.clientY-drag.y)*0.006)); drag={x:e.clientX,y:e.clientY}; this.draw(); };
    this.canvas.onpointerup = e => {if(origin && Math.hypot(e.clientX-origin.x,e.clientY-origin.y)<5){const r=this.canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;const hit=(this.hitTargets||[]).map(h=>({...h,d:Math.hypot(h.x-x,h.y-y)})).sort((a,b)=>a.d-b.d)[0];if(hit?.d<26){this.selected=hit.id;this.selector.value=hit.id;this.fields();this.draw();}}drag=null;origin=null;};
    this.canvas.onpointercancel = () => { drag = null;origin=null; };
    this.canvas.addEventListener("wheel", e => { e.preventDefault(); this.zoom = Math.max(0.3,Math.min(5,this.zoom*Math.exp(-e.deltaY*0.001))); this.draw(); }, {passive:false});
    this.canvas.onkeydown = e => { if (["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key)) { e.preventDefault(); this.rotation += e.key === "ArrowLeft" ? -0.1 : e.key === "ArrowRight" ? 0.1 : 0; this.tilt += e.key === "ArrowUp" ? -0.1 : e.key === "ArrowDown" ? 0.1 : 0; this.draw(); } };
    new ResizeObserver(() => this.draw()).observe(this.canvas);
    hooks.api("/api/ai/status").then(s => { this.aiConfigured = s.configured; this.status.textContent = `${s.message} 模型：${s.model}`; this.update(); }).catch(e => { this.status.textContent=e.message; });
  }
  async load(project) {
    const seq = ++this.sequence; this.loading = true; this.scene = null; this.trace = null; this.draw(); this.update();
    if (this.projectId !== project.id) { this.history = []; this.messages.replaceChildren(); }
    this.projectId = project.id;
    try {
      const data = project.scene ? {scene:project.scene} : await this.hooks.api(`/api/projects/${encodeURIComponent(project.id)}/scene`);
      if (seq !== this.sequence) return;
      this.scene = structuredClone(data.scene); this.trace = data.trace || await this.hooks.api("/api/scene/trace", {scene:this.scene});
      if (seq !== this.sequence) return;
      this.selector.replaceChildren(...this.scene.elements.map(e => { const n = this.make("option", "", `${e.label} · ${e.id}`); n.value=e.id; return n; }));
      if (!this.scene.elements.some(e=>e.id===this.selected)) this.selected=this.scene.elements.find(e=>e.kind==="lens")?.id || this.scene.elements[0].id;
      this.selector.value=this.selected; this.fields();
      Object.entries(this.rayInputs).forEach(([key,n])=>{n.value=this.scene.rays[key];}); this.showTrace();
    } catch(e) { if(seq===this.sequence) { this.summary.textContent=e.message; this.hooks.toast(e.message,true); } }
    finally { if(seq===this.sequence) { this.loading=false; this.update(); this.draw(); } }
  }
  fields() {
    const e = this.scene?.elements.find(e=>e.id===this.selected); this.editor.replaceChildren(); if(!e) return;
    const labels={z_mm:"位置 z（展开轴 mm）",y_mm:"偏心 y（mm）",aperture_mm:"有效孔径全高（mm）",width_mm:"符号厚度（mm）",focal_mm:"焦距（mm）",pitch_mm:"复眼节距（mm）",bend_deg:"理想折转（°，0 或 90）"};
    Object.entries(labels).forEach(([key,label])=>{if(e[key]===undefined)return; const wrap=this.make("label","optics-field",label), input=this.make("input"); input.type="number"; input.step=key==="bend_deg"?"90":"any"; input.value=e[key]; input.dataset.opticalField=key;
      input.oninput=()=>{if(this.loading)return; e[key]=input.value===""?null:Number(input.value);this.changed();}; wrap.append(input);this.editor.append(wrap);});
    this.update();
  }
  changed() {
    this.hooks.edit(structuredClone(this.scene)); this.trace=null; this.warning.replaceChildren(); this.summary.textContent="参数已修改，正在预览…"; this.draw(); this.update();
    clearTimeout(this.timer); const scene=structuredClone(this.scene), seq=++this.sequence;
    this.timer=setTimeout(async()=>{try {const trace=await this.hooks.api("/api/scene/trace",{scene});if(seq!==this.sequence)return;this.trace=trace;this.showTrace();this.draw();}catch(e){if(seq===this.sequence)this.summary.textContent=e.message;}},220);
  }
  add() {
    if(!this.scene || this.scene.elements.length>=32){this.hooks.toast("场景最多支持 32 个元件。",true);return;}
    const list=[...this.scene.elements].sort((a,b)=>a.z_mm-b.z_mm);let i=list.findIndex(e=>e.id===this.selected);i=Math.min(Math.max(0,i),list.length-2);
    const z=(list[i].z_mm+list[i+1].z_mm)/2;if(!Number.isFinite(z)||list[i+1].z_mm-list[i].z_mm<0.00001){this.hooks.toast("相邻元件间距过小，请先调整位置。",true);return;}
    const kind=this.addKind.value;let serial=1;while(this.scene.elements.some(e=>e.id===`${kind}_${serial}`))serial++;
    const item={id:`${kind}_${serial}`,kind,label:`${this.addKind.selectedOptions[0].textContent} ${serial}`,z_mm:z,y_mm:0,aperture_mm:10,width_mm:2};
    if(kind==="lens"||kind==="flyeye")item.focal_mm=20;if(kind==="flyeye")item.pitch_mm=1;if(kind==="prism")item.bend_deg=90;
    this.scene.elements.push(item);this.selected=item.id;const option=this.make("option","",`${item.label} · ${item.id}`);option.value=item.id;this.selector.append(option);this.selector.value=item.id;this.fields();this.changed();
  }
  remove() {
    const item=this.scene?.elements.find(e=>e.id===this.selected);if(!item || ["source","screen"].includes(item.kind))return;
    this.scene.elements=this.scene.elements.filter(e=>e.id!==item.id);this.selector.querySelector(`option[value="${item.id}"]`)?.remove();this.selected=this.scene.elements[0].id;this.selector.value=this.selected;this.fields();this.changed();
  }
  showTrace() {
    if(!this.trace)return; const s=this.trace.summary;
    this.summary.textContent=`近轴代表光线 ${s.launched} 条 · 达屏 ${s.reached} · 截光 ${s.blocked} · 屏上 y：${s.screen_min_y_mm?.toFixed(2) ?? "—"} 至 ${s.screen_max_y_mm?.toFixed(2) ?? "—"} mm`;
    this.warning.replaceChildren(...this.trace.warnings.map(w=>this.make("p","",w)));
  }
  update() {
    const s=this.hooks.state(); const disabled=s.busy || this.loading;
    this.right.querySelectorAll("input,select").forEach(n=>n.disabled=disabled);
    this.addButton.disabled=disabled||!this.scene||this.scene.elements.length>=32;
    this.removeButton.disabled=disabled||!this.scene||["source","screen"].includes(this.scene.elements.find(e=>e.id===this.selected)?.kind);
    this.send.disabled=disabled || s.dirty || !this.aiConfigured || !this.scene;
    this.copy.disabled=disabled || s.dirty || !this.scene;
    this.prompt.disabled=disabled;
    this.send.title=s.dirty?"先保存原型，再让 AI 操作相同版本":"";
  }
  async copyPrompt() {
    const p=this.hooks.state().project; if(!p || this.hooks.state().dirty)return;
    const text=`请通过 optics-workbench MCP 编辑原型 ${p.id}（当前版本 ${p.version}）。先用 optics_get_scene 读取并确认版本，用 optics_trace_scene 预览光扇，再用 optics_apply_design 或 optics_save_scene 保存，使用当前版本校验。指令：${this.prompt.value.trim() || "读取并解释当前光路，指出需要验证的假设。"}`;
    try { await navigator.clipboard.writeText(text); this.hooks.toast("已复制；粘贴到 Codex 对话发送后，工作台会同步新版本。"); } catch { this.prompt.value=text; this.hooks.toast("自动复制不可用，指令已放入输入框，请手动复制。"); }
  }
  async ask() {
    const message=this.prompt.value.trim(); if(!message || this.send.disabled)return;
    const p=this.hooks.state().project; const previous=this.history.slice(-12);
    this.messages.append(this.make("p","optics-message user",message)); this.prompt.value="";
    await this.hooks.busy(async()=>{
      try { const data=await this.hooks.api("/api/ai/chat",{project_id:p.id,version:p.version,message,history:previous});
        this.history.push({role:"user",content:message},{role:"assistant",content:data.reply}); this.history=this.history.slice(-12);
        this.messages.append(this.make("p","optics-message assistant",data.reply)); this.hooks.adopt(data.project); this.hooks.toast("AI 回复已返回；有效设计修改已保存。");
      } catch(e) {this.messages.append(this.make("p","optics-message error",e.message));throw e;}
      finally { this.messages.scrollTop=this.messages.scrollHeight; }
    });
  }
  draw() {
    const rect=this.canvas.getBoundingClientRect(); if(!rect.width)return; const dpr=window.devicePixelRatio||1;
    this.canvas.width=Math.round(rect.width*dpr);this.canvas.height=Math.round(rect.height*dpr);
    const c=this.canvas.getContext("2d");c.scale(dpr,dpr);const W=rect.width,H=rect.height;
    c.fillStyle="#101f2a";c.fillRect(0,0,W,H);
    c.strokeStyle="#253744";c.lineWidth=1;for(let x=0;x<W;x+=32){c.beginPath();c.moveTo(x,0);c.lineTo(x,H);c.stroke();}for(let y=0;y<H;y+=32){c.beginPath();c.moveTo(0,y);c.lineTo(W,y);c.stroke();}
    if(!this.scene){c.fillStyle="#bacbd4";c.fillText("正在载入光路…",24,38);return;}
    const elements=[...this.scene.elements].sort((a,b)=>a.z_mm-b.z_mm);
    if(elements.some(e=>!Number.isFinite(e.z_mm)||!Number.isFinite(e.aperture_mm)))return;
    const min=elements[0].z_mm,max=elements.at(-1).z_mm,span=Math.max(max-min,1), aperture=Math.max(...elements.map(e=>e.aperture_mm),1);
    const folds=elements.filter(e=>e.kind==="prism"&&e.bend_deg===90);
    const world=(z,y,depth=0)=>{let x=0,q=0,start=min,ang=0;for(const f of folds){if(f.z_mm>=z)break;x+=(f.z_mm-start)*Math.cos(ang);q+=(f.z_mm-start)*Math.sin(ang);start=f.z_mm;ang+=Math.PI/2;}x+=(z-start)*Math.cos(ang);q+=(z-start)*Math.sin(ang);return [x-depth*Math.sin(ang),y,q+depth*Math.cos(ang)];};
    const projected=(z,y,depth=0)=>{if(this.mode==="2d")return [z,y];const [x,v,q]=world(z,y,depth);return [x*Math.cos(this.rotation)+q*Math.sin(this.rotation),v*Math.cos(this.tilt)+(q*Math.cos(this.rotation)-x*Math.sin(this.rotation))*Math.sin(this.tilt)];};
    const extents=elements.flatMap(e=>{const a=e.aperture_mm/2,y=e.y_mm||0;return [projected(e.z_mm,y-a,-a),projected(e.z_mm,y+a,a),projected(e.z_mm,y-a,a),projected(e.z_mm,y+a,-a)];});
    const xmin=Math.min(...extents.map(p=>p[0])),xmax=Math.max(...extents.map(p=>p[0])),ymin=Math.min(...extents.map(p=>p[1])),ymax=Math.max(...extents.map(p=>p[1]));
    const scale=Math.min((W-110)/Math.max(xmax-xmin,1),(H-100)/Math.max(ymax-ymin,1))*this.zoom;
    const project=(z,y,depth=0)=>{const p=projected(z,y,depth);return [W/2+(p[0]-(xmin+xmax)/2)*scale,H/2-(p[1]-(ymin+ymax)/2)*scale];};
    const line=(pts,color,width=1)=>{c.beginPath();pts.forEach((p,i)=>{const [x,y]=project(...p);if(i)c.lineTo(x,y);else c.moveTo(x,y);});c.strokeStyle=color;c.lineWidth=width;c.stroke();};
    line(elements.map(e=>[e.z_mm,0]),"#607383",1);
    if(this.trace)this.trace.rays.forEach((r,i)=>line(r.points.map(p=>[p.z_mm,p.y_mm]),r.status==="blocked"?"#e39059aa":["#72dcccaa","#e7c45faa","#83b9f2aa"][i%3],1.2));
    this.hitTargets=[];
    elements.forEach(e=>{const a=e.aperture_mm/2,y=e.y_mm||0;const color=e.id===this.selected?"#fff0a0":e.kind==="source"?"#ffcf76":e.kind==="screen"?"#d0dce6":"#78caca";
      const [hx,hy]=project(e.z_mm,y);this.hitTargets.push({id:e.id,x:hx,y:hy});
      if(this.mode==="3d" && ["lens","flyeye","source","screen"].includes(e.kind)){const pts=[];for(let i=0;i<=48;i++){const t=i/48*Math.PI*2;pts.push([e.z_mm,y+a*Math.cos(t),a*Math.sin(t)]);}line(pts,color,2);}
      line([[e.z_mm,y-a],[e.z_mm,y+a]],color,e.kind==="lens"?4:2);
      if(e.kind==="prism")line([[e.z_mm-e.width_mm,y-a],[e.z_mm+e.width_mm,y],[e.z_mm-e.width_mm,y+a],[e.z_mm-e.width_mm,y-a]],color,2);
      if(e.kind==="flyeye"&&e.pitch_mm>0){for(let v=-a;v<=a && (v+a)/e.pitch_mm<100;v+=e.pitch_mm)line([[e.z_mm-1,y+v],[e.z_mm+1,y+v]],color);}
      const [px,py]=project(e.z_mm,y-a);c.fillStyle=color;c.font="11px sans-serif";c.fillText(e.label,Math.min(W-90,Math.max(8,px-20)),Math.min(H-14,Math.max(20,py+22)));
    });
    c.fillStyle="#9fb4c4";c.font="11px sans-serif";c.fillText(this.mode==="3d"?"3D SYMBOLIC · IDEAL FOLD":"2D · UNFOLDED PARAXIAL",16,22);
  }
};
