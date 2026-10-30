/* Bundled HA custom panel. No CDN, external fonts, token storage or dependencies. */
class QuanyuZhilianPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this.offset = 0;
    this.total = 0;
    this.pageSize = 12;
    this.profiles = [];
    this.gateways = [];
    this.profile = null;
    this.loading = false;
    this.sending = false;
    this.searchId = 0;
    this.detailId = 0;
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;color:var(--primary-text-color,#172b36);background:var(--primary-background-color,#f5f7fa);min-height:100%;font-family:var(--paper-font-body1_-_font-family,system-ui)}
        *{box-sizing:border-box}main{max-width:1240px;margin:auto;padding:28px}header{display:flex;gap:16px;align-items:center;margin-bottom:24px}h1{font-size:26px;margin:0 0 6px}h2{font-size:19px;margin:0 0 16px}p{line-height:1.6;margin:6px 0;color:var(--secondary-text-color,#637582)}
        .tag{font-size:12px;padding:5px 9px;background:var(--secondary-background-color,#e5edf1);border-radius:16px;white-space:nowrap}.grow{flex:1}.card{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dbe3e9);border-radius:14px;padding:20px;margin-bottom:18px}
        label{display:block;font-size:13px;font-weight:600;margin-bottom:8px}input,select,button{font:inherit;color:inherit}input,select{width:100%;min-height:44px;border:1px solid var(--divider-color,#c7d3dc);border-radius:8px;background:var(--card-background-color,#fff);padding:10px}button{cursor:pointer;min-height:42px;padding:9px 16px;border-radius:8px;border:1px solid var(--divider-color,#c7d3dc);background:var(--card-background-color,#fff)}button:hover:not(:disabled){border-color:var(--primary-color,#087f8c)}button:disabled{opacity:.5;cursor:not-allowed}.primary{background:var(--primary-color,#087f8c);color:var(--text-primary-color,#fff);border-color:transparent}.row{display:flex;gap:12px;align-items:end}.search{flex:1}.category{width:170px}.layout{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:12px 0}#results{display:grid;gap:8px}.remote{text-align:left;display:block;width:100%;padding:14px}.remote strong{display:block;margin-bottom:5px}.remote small{display:block;color:var(--secondary-text-color,#637582);word-break:break-word}.remote[aria-pressed=true]{border-color:var(--primary-color,#087f8c);box-shadow:inset 3px 0 var(--primary-color,#087f8c)}.keys{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;max-height:460px;overflow:auto;padding:2px}.key{text-align:left;min-height:70px;overflow-wrap:anywhere}.key small{display:block;font-size:11px;margin-top:5px;color:var(--secondary-text-color,#637582)}#notice{padding:12px 16px;border-radius:8px;margin-bottom:16px;background:var(--secondary-background-color,#e5edf1);line-height:1.5}#notice[data-error=true]{color:var(--error-color,#b3261e)}[hidden]{display:none!important}.empty{padding:25px 4px}#menu{border:0;padding:8px;min-width:44px;font-size:23px}.actions{display:flex;gap:8px}#gateway-status{margin-top:8px;font-size:13px}.hint{font-size:12px;margin-top:14px}.source{font-size:12px;margin-top:22px}
        @media(max-width:800px){main{padding:18px}.layout{grid-template-columns:1fr}.row{flex-wrap:wrap}.search{min-width:180px}.category{flex:1}header{align-items:start}h1{font-size:23px}.tag{display:none}}
      </style>
      <main>
        <header><button id="menu" aria-label="打开侧边栏">☰</button><div class="grow"><h1>红外码库</h1><p>全域智联 · 为房间网关选择遥控器与按键</p></div><span class="tag">本地存储 · 离线可用</span></header>
        <div id="notice" role="status" aria-live="polite" hidden></div>
        <section class="card"><div class="row"><div class="grow"><label for="gateway">发送网关</label><select id="gateway" aria-label="发送网关"></select></div><button id="refresh">刷新网关</button></div><p id="gateway-status"></p></section>
        <div class="layout">
          <section class="card"><h2>选择遥控器</h2><form id="search-form" class="row"><div class="search"><label for="query">品牌或型号</label><input id="query" type="search" placeholder="例如 TCL、Samsung、遥控器型号" maxlength="128"></div><div class="category"><label for="category">设备类型</label><select id="category"><option value="">全部类型</option><option value="ACs">空调</option><option value="TVs">电视</option><option value="Fans">风扇</option><option value="Projectors">投影仪</option><option value="LED_Lighting">灯光</option><option value="Audio_and_Video_Receivers">影音接收器</option></select></div><button class="primary" id="search" type="submit">搜索</button></form><div class="toolbar"><p id="count">正在读取本地库…</p><div class="actions"><button id="prev" aria-label="上一页">←</button><button id="next" aria-label="下一页">→</button></div></div><div id="results"></div><p id="source" class="source"></p></section>
          <section class="card"><h2 id="detail-title">选择一个遥控器</h2><p id="detail-subtitle">左侧搜索品牌或型号，选择后查看按键。</p><div class="toolbar" id="key-tools" hidden><label><input id="supported-only" type="checkbox" style="width:auto;min-height:0"> 只看当前可发送按键</label><span id="key-count"></span></div><div id="keys" class="keys"></div><p class="hint">发送成功表示 CYD 已完成发射，不代表电器已确认执行。请让红外模块对准电器；未支持的编码保留在库中，暂不可发送。</p></section>
        </div>
      </main>`;
    this.$ = (id) => this.shadowRoot.getElementById(id);
    this.$("menu").onclick = () => this.dispatchEvent(new CustomEvent("hass-toggle-menu", {bubbles:true, composed:true}));
    this.$("search-form").onsubmit = (event) => {event.preventDefault(); this.offset=0; this.search();};
    this.$("prev").onclick = () => {this.offset=Math.max(0,this.offset-this.pageSize); this.search();};
    this.$("next").onclick = () => {this.offset+=this.pageSize; this.search();};
    this.$("refresh").onclick = () => this.refreshGateways();
    this.$("gateway").onchange = () => {this.renderGateway(); this.renderKeys();};
    this.$("supported-only").onchange = () => this.renderKeys();
  }
  set hass(value) {
    this._hass=value;
    if(!this.started && this.isConnected){this.started=true; this.start();}
  }
  connectedCallback(){if(this._hass && !this.started){this.started=true;this.start();}}
  disconnectedCallback(){clearInterval(this.timer);this.started=false;}
  start(){this.refreshGateways();this.search();this.timer=setInterval(()=>this.refreshGateways(),20000);}
  async response(service,data={}) {
    const result=await this._hass.callWS({type:"call_service",domain:"quanyu_zhilian",service,service_data:data,return_response:true});
    return result.response;
  }
  notice(message,error=false){this.$("notice").textContent=message;this.$("notice").hidden=!message;this.$("notice").dataset.error=String(error);}
  message(error){return error?.message || String(error);}
  async refreshGateways(){
    try {
      const result=await this.response("ir_gateways");
      const selected=this.$("gateway").value || new URLSearchParams(location.search).get("gateway");
      this.gateways=result.gateways;
      this.$("gateway").replaceChildren();
      for(const gateway of this.gateways){const option=document.createElement("option");option.value=gateway.gateway_id;option.textContent=`${gateway.room && gateway.room!=="Unassigned"?gateway.room+" · ":""}${gateway.gateway_id}${gateway.ready?"":"（未就绪）"}`;this.$("gateway").append(option);}
      if(this.gateways.some(g=>g.gateway_id===selected))this.$("gateway").value=selected;
      if(!this.gateways.length){const option=document.createElement("option");option.textContent="尚未配置网关";option.value="";this.$("gateway").append(option);}
      this.gatewayError=false; this.renderGateway();this.renderKeys();
    }catch(error){this.gatewayError=true;this.$("gateway-status").textContent="网关状态读取失败："+this.message(error);this.renderKeys();}
  }
  currentGateway(){return this.gateways.find(g=>g.gateway_id===this.$("gateway").value);}
  canSend(){const gateway=this.currentGateway();return !this.gatewayError && gateway?.ready && gateway?.ir_send && !this.sending;}
  renderGateway(){const g=this.currentGateway();this.$("gateway-status").textContent=!g?"请在设置 → 设备与服务中添加全域智联网关。":!g.online?"网关离线，码库仍可浏览。":!g.ready?"网关在线，正在等待控制会话就绪。":!g.ir_send?"当前固件未声明红外发送能力。":"已就绪 · 按键将发送到此网关";}
  async search(){
    const id=++this.searchId;this.loading=true;this.updatePaging();this.$("count").textContent="正在搜索…";
    try{
      const result=await this.response("ir_search",{query:this.$("query").value.trim(),category:this.$("category").value,limit:this.pageSize,offset:this.offset});
      if(id!==this.searchId)return;
      this.profiles=result.profiles;this.total=result.total;
      this.$("source").textContent=`Flipper-IRDB · ${Number(result.source.profiles).toLocaleString()} 个遥控器 · ${Number(result.source.signals).toLocaleString()} 条按键记录 · 快照 ${result.source.revision.slice(0,8)}`;
      this.$("count").textContent=this.total?`共 ${this.total.toLocaleString()} 个 · ${this.offset+1}–${Math.min(this.offset+this.pageSize,this.total)}`:"没有找到匹配的遥控器，试试品牌名或其他型号。";
      this.renderResults();
    }catch(error){if(id===this.searchId){this.$("count").textContent="搜索失败";this.notice("本地码库读取失败："+this.message(error),true);}}
    finally{if(id===this.searchId){this.loading=false;this.updatePaging();}}
  }
  updatePaging(){this.$("prev").disabled=this.loading||!this.offset;this.$("next").disabled=this.loading||this.offset+this.pageSize>=this.total;this.$("search").disabled=this.loading;}
  renderResults(){
    this.$("results").replaceChildren();
    for(const profile of this.profiles){const button=document.createElement("button");button.className="remote";button.setAttribute("aria-pressed",String(this.profile?.id===profile.id));const title=document.createElement("strong");title.textContent=profile.model;const sub=document.createElement("small");sub.textContent=`${profile.brand} · ${profile.category} · ${profile.signal_count} 个按键`;button.append(title,sub);button.onclick=()=>this.inspect(profile.id);this.$("results").append(button);}
  }
  async inspect(profileId){
    const id=++this.detailId;this.profile=null;this.renderKeys();this.$("detail-title").textContent="正在读取遥控器…";
    try{const profile=await this.response("ir_inspect",{profile_id:profileId});if(id!==this.detailId)return;this.profile=profile;this.$("detail-title").textContent=profile.model;this.$("detail-subtitle").textContent=`${profile.brand} · ${profile.path}`;this.renderResults();this.renderKeys();}
    catch(error){if(id===this.detailId){this.$("detail-title").textContent="遥控器读取失败";this.notice(this.message(error),true);}}
  }
  limitation(reason){
    if(!reason)return "原始波形 · 点击发送";
    const key=reason.split(":")[0];
    return ({PARSED_PROTOCOL_NOT_SUPPORTED:"协议编码暂未适配",UNSUPPORTED_FREQUENCY:"载波频率超出当前固件范围",UNSUPPORTED_DUTY_CYCLE:"占空比暂不兼容",RAW_LENGTH_NOT_SUPPORTED:"波形长度超出当前固件范围",RAW_TIMING_NOT_SUPPORTED:"波形间隔超出当前固件范围",INVALID_RAW_RECORD:"原始记录不完整"})[key]||"当前固件暂不支持";
  }
  renderKeys(){
    this.$("keys").replaceChildren();this.$("key-tools").hidden=!this.profile;
    if(!this.profile)return;
    const supported=this.profile.signals.filter(s=>s.cyd_sendable);
    this.$("key-count").textContent=`可发 ${supported.length} / ${this.profile.signals.length}`;
    const signals=this.$("supported-only").checked?supported:this.profile.signals;
    for(const signal of signals){const button=document.createElement("button");button.className="key";button.disabled=!signal.cyd_sendable||!this.canSend();const title=document.createElement("span");title.textContent=signal.name;const sub=document.createElement("small");sub.textContent=this.limitation(signal.limitation);button.title=signal.limitation||signal.name;button.append(title,sub);button.onclick=()=>this.send(signal);this.$("keys").append(button);}
    if(!signals.length){const p=document.createElement("p");p.textContent="此遥控器暂无当前固件可发送的按键，可取消筛选查看全部记录。";this.$("keys").append(p);}
  }
  async send(signal){
    if(!this.canSend()||!this.profile||!signal.cyd_sendable)return;
    const gatewayId=this.$("gateway").value, profileId=this.profile.id;
    this.sending=true;this.renderKeys();this.notice(`正在通过 ${gatewayId} 发送「${signal.name}」…`);
    try{await this._hass.callService("quanyu_zhilian","ir_send",{gateway_id:gatewayId,profile_id:profileId,signal_index:signal.index});this.notice(`「${signal.name}」已发送，CYD 已回执。请观察电器是否响应。`);}
    catch(error){this.notice(`「${signal.name}」发送未确认：${this.message(error)}`,true);}
    finally{this.sending=false;this.renderKeys();}
  }
}
if(!customElements.get("quanyu-zhilian-panel"))customElements.define("quanyu-zhilian-panel",QuanyuZhilianPanel);
