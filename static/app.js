const defaultTexts = ["おはよう！","ありがとう","了解！","おつかれさま","やったー！","ごめんね","おやすみ","今から帰る"];
const sessionBase = document.querySelector('meta[name="session-base"]').content;
let catalog = [];
const categoryNames = {reply:"返事",greeting:"挨拶",thanks:"感謝・謝罪",feeling:"気持ち",family:"家族連絡",request:"予定・お願い",support:"応援・労い",daily:"体調・生活"};
let activeCategory = "reply";
let duration = 0;
let active = 0;
let playbackTimer = null;
let selectedFile = null;
let jobId = null;
let sourceWidth = 1;
let sourceHeight = 1;
const layouts = [
  {id:"wide",box:[12,12,308,224]}, {id:"circle",box:[51,5,269,223]},
  {id:"portrait",box:[77,4,243,224]}, {id:"arch",box:[55,4,265,224]},
  {id:"heart",box:[45,2,275,224]}, {id:"star",box:[48,1,272,225]},
  {id:"oval",box:[30,15,290,215]}, {id:"polaroid",box:[42,10,278,207]},
  {id:"speech",box:[28,7,292,213]}, {id:"scallop",box:[25,8,295,218]},
  {id:"diamond",box:[57,2,263,224]}, {id:"hex",box:[38,7,282,218]},
  {id:"film",box:[18,31,302,205]}, {id:"phone",box:[91,3,229,224]},
  {id:"badge",box:[49,3,271,224]}, {id:"wave",box:[20,15,300,215]}
  ,{id:"capsule",box:[22,42,298,192]}, {id:"vertical_oval",box:[82,2,238,224]}
  ,{id:"shield",box:[59,2,261,224]}, {id:"clover",box:[48,2,272,224]}
  ,{id:"octagon",box:[43,4,277,224]}, {id:"ticket",box:[20,30,300,204]}
  ,{id:"book",box:[28,13,292,216]}, {id:"cloud",box:[27,14,293,214]}
  ,{id:"burst",box:[43,1,277,225]}, {id:"drop",box:[69,1,251,224]}
  ,{id:"egg",box:[74,1,246,224]}, {id:"trapezoid",box:[37,12,283,218]}
  ,{id:"tv",box:[25,20,295,207]}, {id:"stamp",box:[50,2,270,224]}
  ,{id:"flower_shape",box:[48,2,272,224]}, {id:"leaf_shape",box:[49,2,271,224]}
];
const layoutNames={wide:"横長",circle:"円",portrait:"縦角丸",arch:"アーチ",heart:"ハート",star:"星",oval:"横楕円",polaroid:"ポラロイド",speech:"吹き出し",scallop:"スカラップ",diamond:"ひし形",hex:"六角形",film:"フィルム",phone:"スマホ縦",badge:"バッジ",wave:"波型",capsule:"カプセル",vertical_oval:"縦楕円",shield:"盾",clover:"四つ葉",octagon:"八角形",ticket:"チケット",book:"本",cloud:"雲",burst:"爆発",drop:"しずく",egg:"たまご",trapezoid:"台形",tv:"テレビ",stamp:"切手",flower_shape:"花",leaf_shape:"葉"};
const starterFrames = ["morning","thanks","roger","otsukare","yay","sorry","goodnight","goinghome"];
const starterLayouts = ["circle","heart","speech","capsule","star","cloud","vertical_oval","wide"];
const slots = defaultTexts.map((text,i)=>({text,start:i*2,duration:2,focusX:.5,focusY:.5,zoom:1,theme:starterFrames[i],layout:starterLayouts[i]||"wide"}));

const input = document.getElementById("videoInput");
const video = document.getElementById("preview");
const workspace = document.getElementById("workspace");
const caption = document.getElementById("previewCaption");
const captionBox = document.querySelector(".preview-caption");
const effectCanvas = document.getElementById("previewEffect");
const videoViewport = document.getElementById("videoViewport");
const chooseButton = document.getElementById("chooseVideoButton");
const sourceStatus = document.getElementById("sourceStatus");
const updatePanel = document.getElementById("updatePanel");
const updateTitle = document.getElementById("updateTitle");
const updateMessage = document.getElementById("updateMessage");
const installUpdateButton = document.getElementById("installUpdateButton");

fetch("/static/frame_catalog.json").then(r=>r.json()).then(data=>{catalog=data;renderFrameCategories();renderFrameGrid();renderLayoutGrid();requestAnimationFrame(animatePreviews);});

chooseButton.addEventListener("click",(event)=>{event.preventDefault();event.stopPropagation();input.click();});
input.addEventListener("change",async(event)=>{
  event.preventDefault(); event.stopPropagation();
  selectedFile=input.files[0]; if(!selectedFile)return;
  jobId=null; workspace.classList.add("hidden"); chooseButton.disabled=true;
  document.getElementById("fileLabel").textContent=selectedFile.name;
  sourceStatus.textContent="Mac内で動画を読み込み中…";
  const form=new FormData();form.append("video",selectedFile);
  try{
    const response=await fetch(`${sessionBase}/prepare`,{method:"POST",body:form});
    if(!response.ok){const data=await response.json();throw new Error(data.error||"動画を読み込めませんでした。");}
    const data=await response.json();jobId=data.jobId;duration=Number(data.duration);sourceWidth=Number(data.width)||1;sourceHeight=Number(data.height)||1;video.src=data.previewUrl;
    video.onloadedmetadata=()=>{
    slots.forEach((s,i)=>{ s.start=Math.min(Math.max(0,i*(Math.max(1,duration-2)/7)),Math.max(0,duration-s.duration)); });
    workspace.classList.remove("hidden"); renderTabs(); renderEditor(); seekActive();
    sourceStatus.textContent="読み込み完了。下で8個を設定してください。";
    };
  }catch(error){sourceStatus.textContent=`エラー：${error.message}`;}
  finally{chooseButton.disabled=false;}
});

function renderTabs(){
  const el=document.getElementById("tabs"); el.innerHTML="";
  slots.forEach((_,i)=>{ const b=document.createElement("button"); b.className="tab"+(i===active?" active":""); b.textContent=i+1; b.onclick=()=>{active=i;renderTabs();renderEditor();seekActive();}; el.appendChild(b); });
}

function row(label,type,value,min,max,step,key){
  if(type==="text") return `<label class="control">${label}<input data-key="${key}" type="text" value="${escapeHtml(value)}" maxlength="18"></label>`;
  return `<label class="control">${label}<div class="range-row"><input data-key="${key}" type="range" value="${value}" min="${min}" max="${max}" step="${step}"><span class="value" data-value="${key}">${formatValue(key,value)}</span></div></label>`;
}

function renderEditor(){
  const s=slots[active], maxStart=Math.max(0,duration-s.duration);
  document.getElementById("slotEditor").innerHTML=`<div class="editor-grid">
    ${row("表示する文字","text",s.text,0,0,0,"text")}<div></div>
    ${row("開始位置","range",Math.min(s.start,maxStart),0,maxStart,.1,"start")}${row("長さ（LINE仕様：整数秒）","range",s.duration,1,Math.min(4,Math.floor(duration)),1,"duration")}
    ${row("横位置","range",s.focusX,0,1,.01,"focusX")}${row("縦位置","range",s.focusY,0,1,.01,"focusY")}
    ${row("ズーム","range",s.zoom,1,2.2,.05,"zoom")}
  </div>`;
  document.querySelectorAll("[data-key]").forEach(el=>el.addEventListener("input",()=>{
    const key=el.dataset.key; slots[active][key]=(key==="text"||key==="theme")?el.value:Number(el.value);
    if(key==="duration") slots[active].start=Math.min(slots[active].start,Math.max(0,duration-slots[active].duration));
    if(key==="start") video.currentTime=Math.min(slots[active].start,duration||0);
    const valueEl=document.querySelector(`[data-value="${key}"]`); if(valueEl)valueEl.textContent=formatValue(key,slots[active][key]);
    updatePreview();
  }));
  updatePreview();
  renderFrameGrid();
  renderLayoutGrid();
}

function formatValue(key,value){ if(key==="start"||key==="duration")return `${Number(value).toFixed(key==="start"?1:0)}秒`; if(key==="zoom")return `${Number(value).toFixed(2)}×`; return `${Math.round(Number(value)*100)}%`; }
function escapeHtml(v){return String(v).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function seekActive(){ video.currentTime=Math.min(slots[active].start,duration||0); updatePreview(); }
function presetLayout(preset,layoutId){const explicit=layouts.find(l=>l.id===layoutId);if(explicit)return explicit;const index=Math.max(0,catalog.findIndex(p=>p.id===preset?.id));return layouts[index%layouts.length];}
function clipForLayout(id){
  const clips={circle:"circle(50%)",oval:"ellipse(50% 50%)",portrait:"inset(0 round 34%)",phone:"inset(0 round 34%)",arch:"inset(0 round 50% 50% 12% 12%)",
    heart:"polygon(50% 98%,6% 45%,8% 20%,26% 4%,50% 22%,74% 4%,92% 20%,94% 45%)",
    star:"polygon(50% 0%,61% 34%,98% 36%,69% 57%,79% 94%,50% 72%,21% 94%,31% 57%,2% 36%,39% 34%)",
    speech:"polygon(0 0,100% 0,100% 82%,82% 82%,70% 100%,66% 82%,0 82%)",diamond:"polygon(50% 0,100% 50%,50% 100%,0 50%)",
    hex:"polygon(24% 0,76% 0,100% 50%,76% 100%,24% 100%,0 50%)",badge:"polygon(16% 0,84% 0,100% 45%,72% 90%,50% 100%,28% 90%,0 45%)",
    wave:"polygon(0 7%,12% 1%,25% 7%,38% 1%,50% 7%,63% 1%,76% 7%,88% 1%,100% 7%,100% 93%,88% 99%,76% 93%,63% 99%,50% 93%,38% 99%,25% 93%,12% 99%,0 93%)",
    vertical_oval:"ellipse(50% 50%)",egg:"ellipse(50% 50%)",shield:"polygon(0 0,100% 0,88% 66%,50% 100%,12% 66%)",clover:"circle(49%)",octagon:"polygon(28% 0,72% 0,100% 28%,100% 72%,72% 100%,28% 100%,0 72%,0 28%)",ticket:"inset(0 round 18px)",book:"polygon(0 8%,48% 2%,50% 13%,52% 2%,100% 8%,94% 96%,52% 84%,50% 95%,48% 84%,6% 96%)",cloud:"ellipse(50% 45%)",burst:"polygon(50% 0,58% 26%,74% 7%,72% 34%,96% 22%,78% 43%,100% 50%,78% 58%,96% 79%,72% 67%,74% 94%,58% 74%,50% 100%,42% 74%,26% 94%,28% 67%,4% 79%,22% 58%,0 50%,22% 43%,4% 22%,28% 34%,26% 7%,42% 26%)",drop:"polygon(50% 0,80% 36%,100% 70%,88% 93%,50% 100%,12% 93%,0 70%,20% 36%)",trapezoid:"polygon(18% 0,82% 0,100% 100%,0 100%)",tv:"inset(0 round 28px)",stamp:"inset(0 round 4px)",flower_shape:"circle(49%)",leaf_shape:"ellipse(50% 42%)",capsule:"inset(0 round 999px)"};
  return clips[id]||"inset(0 round 25px)";
}
function maskSvg(id){
  let body="";
  if(id==="clover")body='<circle cx="34" cy="32" r="28"/><circle cx="66" cy="32" r="28"/><circle cx="34" cy="66" r="28"/><circle cx="66" cy="66" r="28"/>';
  else if(id==="cloud")body='<rect x="6" y="30" width="88" height="58" rx="16"/><circle cx="24" cy="38" r="20"/><circle cx="48" cy="25" r="27"/><circle cx="74" cy="38" r="21"/>';
  else if(id==="flower_shape")body=Array.from({length:8},(_,i)=>{const a=i*Math.PI/4;return `<circle cx="${50+Math.cos(a)*22}" cy="${50+Math.sin(a)*22}" r="24"/>`;}).join("")+'<circle cx="50" cy="50" r="27"/>';
  else if(id==="scallop"||id==="stamp"){const step=id==="stamp"?10:14,r=id==="stamp"?7:10;body='<rect x="5" y="5" width="90" height="90" rx="10"/>';for(let n=8;n<=92;n+=step)body+=`<circle cx="${n}" cy="5" r="${r}"/><circle cx="${n}" cy="95" r="${r}"/><circle cx="5" cy="${n}" r="${r}"/><circle cx="95" cy="${n}" r="${r}"/>`;}
  else if(id==="book")body='<polygon points="0,8 48,2 50,13 52,2 100,8 94,96 52,84 50,95 48,84 6,96"/>';
  else if(id==="tv")body='<rect x="0" y="0" width="100" height="86" rx="15"/><polygon points="37,82 63,82 72,100 28,100"/>';
  else if(id==="drop")body='<path d="M50 0 C100 48 100 82 50 100 C0 82 0 48 50 0Z"/>';
  else if(id==="egg")body='<path d="M50 0 C90 18 100 70 50 100 C0 70 10 18 50 0Z"/>';
  else if(id==="leaf_shape")body='<path d="M0 50 C28 -2 72 -2 100 50 C72 102 28 102 0 50Z"/>';
  if(!body)return null;return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g fill="white">${body}</g></svg>`;
}
function updateVideoGeometry(s,preset){
  const layout=presetLayout(preset,s.layout),[x1,y1,x2,y2]=layout.box,w=x2-x1,h=y2-y1;
  videoViewport.style.left=`${x1}px`;videoViewport.style.top=`${y1}px`;videoViewport.style.width=`${w}px`;videoViewport.style.height=`${h}px`;
  const svg=maskSvg(layout.id);if(svg){const url=`url("data:image/svg+xml,${encodeURIComponent(svg)}")`;videoViewport.style.clipPath="none";videoViewport.style.webkitMaskImage=url;videoViewport.style.maskImage=url;videoViewport.style.webkitMaskSize="100% 100%";videoViewport.style.maskSize="100% 100%";videoViewport.style.webkitMaskRepeat="no-repeat";videoViewport.style.maskRepeat="no-repeat";}else{videoViewport.style.webkitMaskImage="none";videoViewport.style.maskImage="none";videoViewport.style.clipPath=clipForLayout(layout.id);}
  const scale=Math.max(w/sourceWidth,h/sourceHeight)*s.zoom,displayW=sourceWidth*scale,displayH=sourceHeight*scale;
  video.style.width=`${displayW}px`;video.style.height=`${displayH}px`;video.style.left=`${-(displayW-w)*s.focusX}px`;video.style.top=`${-(displayH-h)*s.focusY}px`;video.style.transform="none";
}
function updatePreview(){
  const s=slots[active], preset=catalog.find(p=>p.id===s.theme); caption.textContent=s.text||"文字を入力";
  const color=preset?.primary||"#388cff"; captionBox.style.borderColor=color;
  updateVideoGeometry(s,preset);
  document.getElementById("timeReadout").textContent=`${video.currentTime.toFixed(1)} / ${duration.toFixed(1)}秒`;
}
video.addEventListener("timeupdate",updatePreview);
document.getElementById("playSelection").onclick=()=>{
  clearTimeout(playbackTimer); const s=slots[active]; video.currentTime=s.start; video.play();
  playbackTimer=setTimeout(()=>video.pause(),s.duration*1000);
};

function renderFrameCategories(){
  const root=document.getElementById("frameCategories"); if(!root)return; root.innerHTML="";
  Object.entries(categoryNames).forEach(([id,name])=>{const b=document.createElement("button");b.className="category-button"+(id===activeCategory?" active":"");b.textContent=name;b.onclick=()=>{activeCategory=id;renderFrameCategories();renderFrameGrid();};root.appendChild(b);});
}

function renderFrameGrid(){
  if(!catalog.length)return; const root=document.getElementById("frameGrid"); root.innerHTML="";
  const selected=catalog.find(p=>p.id===slots[active].theme); document.getElementById("selectedFrameName").textContent=selected?.name||"";
  catalog.filter(p=>p.category===activeCategory).forEach(p=>{const b=document.createElement("button");b.className="frame-card"+(p.id===slots[active].theme?" selected":"");b.dataset.preset=p.id;b.innerHTML=`<canvas width="120" height="102"></canvas><span>${p.name}</span>`;b.onclick=()=>{slots[active].theme=p.id;slots[active].text=p.defaultText||p.name;renderEditor();updatePreview();renderFrameGrid();};root.appendChild(b);});
}

function renderLayoutGrid(){
  if(!catalog.length)return;const root=document.getElementById("layoutGrid");root.innerHTML="";document.getElementById("selectedLayoutName").textContent=layoutNames[slots[active].layout]||"";
  const preset=catalog.find(p=>p.id===slots[active].theme)||catalog[0];
  layouts.forEach(layout=>{const b=document.createElement("button");b.className="layout-card"+(layout.id===slots[active].layout?" selected":"");b.dataset.layout=layout.id;b.innerHTML=`<canvas width="120" height="102"></canvas><span>${layoutNames[layout.id]}</span>`;b.onclick=()=>{slots[active].layout=layout.id;renderLayoutGrid();renderFrameGrid();updatePreview();};root.appendChild(b);const c=b.querySelector("canvas");drawEffect(c.getContext("2d"),preset,0,c.width,c.height,true,layout.id);});
}

function rgba(hex,a=1){const n=parseInt(hex.slice(1),16);return `rgba(${n>>16},${(n>>8)&255},${n&255},${a})`;}
function dot(ctx,x,y,r,color){ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();}
function heart(ctx,x,y,s,color){ctx.save();ctx.translate(x,y);ctx.scale(s,s);ctx.beginPath();ctx.moveTo(0,3);ctx.bezierCurveTo(-8,-3,-5,-10,0,-5);ctx.bezierCurveTo(5,-10,8,-3,0,5);ctx.fillStyle=color;ctx.fill();ctx.restore();}
function roundedRectPath(path,x,y,w,h,r){path.moveTo(x+r,y);path.lineTo(x+w-r,y);path.quadraticCurveTo(x+w,y,x+w,y+r);path.lineTo(x+w,y+h-r);path.quadraticCurveTo(x+w,y+h,x+w-r,y+h);path.lineTo(x+r,y+h);path.quadraticCurveTo(x,y+h,x,y+h-r);path.lineTo(x,y+r);path.quadraticCurveTo(x,y,x+r,y);path.closePath();}
function layoutPath(p,w,h,layoutId){
  const layout=presetLayout(p,layoutId),sX=w/320,sY=h/270,[a,b,c,d]=layout.box.map((v,i)=>v*(i%2?sY:sX)),bw=c-a,bh=d-b,path=new Path2D(),id=layout.id;
  if(id==="circle"||id==="oval")path.ellipse(a+bw/2,b+bh/2,bw/2,bh/2,0,0,Math.PI*2);
  else if(id==="heart"){path.moveTo(a+bw/2,b+bh);path.bezierCurveTo(a-bw*.05,b+bh*.56,a+bw*.02,b+bh*.12,a+bw*.27,b+bh*.08);path.bezierCurveTo(a+bw*.43,b+bh*.07,a+bw*.5,b+bh*.22,a+bw*.5,b+bh*.22);path.bezierCurveTo(a+bw*.5,b+bh*.22,a+bw*.57,b+bh*.07,a+bw*.73,b+bh*.08);path.bezierCurveTo(a+bw*.98,b+bh*.12,a+bw*1.05,b+bh*.56,a+bw/2,b+bh);}
  else if(id==="star"){for(let i=0;i<10;i++){const r=(i%2?0.26:0.49)*Math.min(bw,bh),ang=-Math.PI/2+i*Math.PI/5,x=a+bw/2+Math.cos(ang)*r,y=b+bh/2+Math.sin(ang)*r;i?path.lineTo(x,y):path.moveTo(x,y);}path.closePath();}
  else if(id==="diamond") {path.moveTo(a+bw/2,b);path.lineTo(c,b+bh/2);path.lineTo(a+bw/2,d);path.lineTo(a,b+bh/2);path.closePath();}
  else if(id==="hex") {path.moveTo(a+bw*.24,b);path.lineTo(a+bw*.76,b);path.lineTo(c,b+bh/2);path.lineTo(a+bw*.76,d);path.lineTo(a+bw*.24,d);path.lineTo(a,b+bh/2);path.closePath();}
  else if(id==="octagon"){path.moveTo(a+bw*.28,b);path.lineTo(a+bw*.72,b);path.lineTo(c,b+bh*.28);path.lineTo(c,b+bh*.72);path.lineTo(a+bw*.72,d);path.lineTo(a+bw*.28,d);path.lineTo(a,b+bh*.72);path.lineTo(a,b+bh*.28);path.closePath();}
  else if(id==="clover"){[[.34,.32],[.66,.32],[.34,.66],[.66,.66]].forEach(([x,y])=>path.ellipse(a+bw*x,b+bh*y,bw*.28,bh*.28,0,0,Math.PI*2));}
  else if(id==="cloud"){roundedRectPath(path,a+bw*.06,b+bh*.3,bw*.88,bh*.58,Math.min(bw,bh)*.16);[[.24,.38,.2],[.48,.25,.27],[.74,.38,.21]].forEach(([x,y,r])=>path.ellipse(a+bw*x,b+bh*y,bw*r,bh*r,0,0,Math.PI*2));}
  else if(id==="flower_shape"){for(let i=0;i<8;i++){const q=i*Math.PI/4;path.ellipse(a+bw/2+Math.cos(q)*bw*.22,b+bh/2+Math.sin(q)*bh*.22,bw*.24,bh*.24,0,0,Math.PI*2);}path.ellipse(a+bw/2,b+bh/2,bw*.27,bh*.27,0,0,Math.PI*2);}
  else if(id==="shield"){path.moveTo(a,b);path.lineTo(c,b);path.lineTo(a+bw*.88,b+bh*.66);path.lineTo(a+bw/2,d);path.lineTo(a+bw*.12,b+bh*.66);path.closePath();}
  else if(id==="trapezoid"){path.moveTo(a+bw*.18,b);path.lineTo(a+bw*.82,b);path.lineTo(c,d);path.lineTo(a,d);path.closePath();}
  else if(id==="book"){path.moveTo(a,b+bh*.08);path.lineTo(a+bw*.48,b+bh*.02);path.lineTo(a+bw/2,b+bh*.13);path.lineTo(a+bw*.52,b+bh*.02);path.lineTo(c,b+bh*.08);path.lineTo(a+bw*.94,b+bh*.96);path.lineTo(a+bw*.52,b+bh*.84);path.lineTo(a+bw/2,b+bh*.95);path.lineTo(a+bw*.48,b+bh*.84);path.lineTo(a+bw*.06,b+bh*.96);path.closePath();}
  else if(id==="burst"){for(let i=0;i<32;i++){const r=(i%2?.34:.49)*Math.min(bw,bh),ang=-Math.PI/2+i*Math.PI/16,x=a+bw/2+Math.cos(ang)*r,y=b+bh/2+Math.sin(ang)*r;i?path.lineTo(x,y):path.moveTo(x,y);}path.closePath();}
  else if(id==="drop"){path.moveTo(a+bw/2,b);path.bezierCurveTo(c,b+bh*.48,c,b+bh*.82,a+bw/2,d);path.bezierCurveTo(a,b+bh*.82,a,b+bh*.48,a+bw/2,b);path.closePath();}
  else if(id==="egg"){path.moveTo(a+bw/2,b);path.bezierCurveTo(a+bw*.9,b+bh*.18,c,b+bh*.7,a+bw/2,d);path.bezierCurveTo(a,b+bh*.7,a+bw*.1,b+bh*.18,a+bw/2,b);path.closePath();}
  else if(id==="leaf_shape"){path.moveTo(a,b+bh/2);path.bezierCurveTo(a+bw*.28,b-bh*.02,a+bw*.72,b-bh*.02,c,b+bh/2);path.bezierCurveTo(a+bw*.72,d+bh*.02,a+bw*.28,d+bh*.02,a,b+bh/2);path.closePath();}
  else if(id==="tv"){roundedRectPath(path,a,b,bw,bh*.86,Math.min(bw,bh)*.15);path.moveTo(a+bw*.37,b+bh*.82);path.lineTo(a+bw*.63,b+bh*.82);path.lineTo(a+bw*.72,d);path.lineTo(a+bw*.28,d);path.closePath();}
  else if(id==="speech"){roundedRectPath(path,a,b,bw,bh*.86,Math.min(bw,bh)*.16);path.moveTo(a+bw*.62,b+bh*.76);path.lineTo(a+bw*.82,d);path.lineTo(a+bw*.77,b+bh*.7);path.closePath();}
  else if(id==="badge"){path.moveTo(a+bw*.16,b);path.lineTo(a+bw*.84,b);path.lineTo(c,b+bh*.45);path.lineTo(a+bw*.72,b+bh*.9);path.lineTo(a+bw/2,d);path.lineTo(a+bw*.28,b+bh*.9);path.lineTo(a,b+bh*.45);path.closePath();}
  else if(id==="wave"){path.moveTo(a,b+bh*.07);for(let i=0;i<=20;i++)path.lineTo(a+bw*i/20,b+bh*(.04+.04*Math.sin(i*Math.PI/2)));path.lineTo(c,b+bh*.93);for(let i=20;i>=0;i--)path.lineTo(a+bw*i/20,b+bh*(.96+.04*Math.sin(i*Math.PI/2)));path.closePath();}
  else if(["circle","oval","vertical_oval"].includes(id))path.ellipse(a+bw/2,b+bh/2,bw/2,bh/2,0,0,Math.PI*2);
  else {roundedRectPath(path,a,b,bw,bh,id==="capsule"?bh/2:id==="arch"?Math.min(bw,bh)*.42:id==="phone"||id==="portrait"?Math.min(bw,bh)*.32:id==="scallop"?Math.min(bw,bh)*.18:id==="film"||id==="polaroid"?5:Math.min(bw,bh)*.1);}
  return path;
}
function drawEffect(ctx,p,t,w,h,thumbnail=false,layoutId){
  ctx.clearRect(0,0,w,h); const a=p.primary,b=p.secondary,phase=t/900,path=layoutPath(p,w,h,layoutId);
  if(thumbnail){ctx.save();ctx.clip(path);ctx.fillStyle="#607da8";ctx.fillRect(0,0,w,h);dot(ctx,w*.5,h*.34,w*.13,"#f5c49d");ctx.fillStyle="#fc8084";ctx.fillRect(w*.34,h*.47,w*.32,h*.38);ctx.restore();}
  ctx.strokeStyle=rgba(a,.98);ctx.lineWidth=Math.max(3,w/48);ctx.stroke(path);
  for(let i=0;i<10;i++){const q=phase+i*.63,x=w*(.08+.84*((i*.37+q*.04)%1)),y=h*(.1+.68*((i*.23+q*.06)%1));
    if(["heart","heartshower","lace"].includes(p.effect))heart(ctx,x,y,Math.max(.45,w/180),rgba(i%2?a:b,.9));
    else if(["bubble","water","snow"].includes(p.effect)){ctx.beginPath();ctx.arc(x,y,3+(i%3)*2,0,Math.PI*2);ctx.strokeStyle=rgba(i%2?a:b,.9);ctx.lineWidth=2;ctx.stroke();}
    else if(["petals","flower","leaf"].includes(p.effect)){ctx.save();ctx.translate(x,y);ctx.rotate(q);ctx.fillStyle=rgba(i%2?a:b,.9);ctx.fillRect(-2,-5,4,10);ctx.restore();}
    else if(["pixel","confetti","party","candy"].includes(p.effect)){ctx.save();ctx.translate(x,y);ctx.rotate(q);ctx.fillStyle=rgba(i%2?a:b,.95);ctx.fillRect(-3,-5,6,10);ctx.restore();}
    else dot(ctx,x,y,2.5+(i%3),rgba(i%2?a:b,.95));
  }
  if(["bunny","cat","bear","crown","angel","moon","sun","rainbow","cloud","ribbon"].includes(p.effect)){
    ctx.fillStyle=rgba(b,.95);ctx.font=`bold ${Math.round(w*.17)}px sans-serif`;ctx.textAlign="center";
    const icons={bunny:"♡",cat:"▲  ▲",bear:"●  ●",crown:"♛",angel:"⌒   ⌒",moon:"☾",sun:"☀",rainbow:"⌒",cloud:"☁",ribbon:"∞"};ctx.fillText(icons[p.effect]||"✦",w/2,h*.18);
  }
}

function animatePreviews(now){
  if(catalog.length){const s=catalog.find(p=>p.id===slots[active].theme);if(s)drawEffect(effectCanvas.getContext("2d"),s,now,320,270,false,slots[active].layout);
    document.querySelectorAll(".frame-card").forEach(card=>{const p=catalog.find(x=>x.id===card.dataset.preset),c=card.querySelector("canvas");if(p&&c)drawEffect(c.getContext("2d"),p,now,c.width,c.height,true,slots[active].layout);});}
  requestAnimationFrame(animatePreviews);
}

document.getElementById("renderButton").onclick=async()=>{
  const status=document.getElementById("status"), button=document.getElementById("renderButton");
  if(!jobId){status.textContent="動画を選択し、読み込み完了まで待ってください。";return;}
  if(!document.getElementById("privacyCheck").checked){status.textContent="プライバシー確認にチェックしてください。";return;}
  if(slots.some(s=>!s.text.trim())){status.textContent="8個すべてに文字を入力してください。";return;}
  button.disabled=true; status.textContent="Mac内でAPNGを生成中…\n動画の長さにより数分かかります。";
  const form=new FormData(); form.append("jobId",jobId); form.append("config",JSON.stringify({slots}));
  try{
    const response=await fetch(`${sessionBase}/render`,{method:"POST",body:form});
    if(!response.ok){const data=await response.json();throw new Error(data.error||"生成に失敗しました。");}
    const blob=await response.blob(), url=URL.createObjectURL(blob), a=document.createElement("a");
    a.href=url;a.download="LINE_APNG_8.zip";a.click();URL.revokeObjectURL(url);
    status.textContent="完了：LINE_APNG_8.zipを保存しました。";
  }catch(error){status.textContent=`エラー：${error.message}`;}finally{button.disabled=false;}
};

document.getElementById("closeUpdateButton").onclick=()=>updatePanel.classList.add("hidden");
document.getElementById("checkUpdateButton").onclick=async()=>{
  updatePanel.classList.remove("hidden");installUpdateButton.classList.add("hidden");
  updateTitle.textContent="更新を確認しています";
  updateMessage.textContent="GitHubからプログラムの更新情報だけを取得します。動画は送信されません。";
  try{
    const response=await fetch(`${sessionBase}/update/check`,{method:"POST"});
    const data=await response.json();if(!response.ok)throw new Error(data.error||"更新を確認できませんでした。");
    if(data.available){
      updateTitle.textContent=`新しいバージョン ${data.latestVersion}`;
      updateMessage.textContent=`${data.notes}\n\n更新ZIPは電子署名と改変検査を通過した場合だけ適用されます。`;
      installUpdateButton.classList.remove("hidden");
    }else{
      updateTitle.textContent="最新バージョンです";
      updateMessage.textContent=`現在のバージョン：${data.currentVersion}\n動画や作業データはGitHubへ送信していません。`;
    }
  }catch(error){updateTitle.textContent="更新を確認できませんでした";updateMessage.textContent=error.message;}
};
installUpdateButton.onclick=async()=>{
  installUpdateButton.disabled=true;updateTitle.textContent="安全性を確認しています";
  updateMessage.textContent="更新ZIPの電子署名と内容を検査しています。動画は送信されません。";
  try{
    const response=await fetch(`${sessionBase}/update/install`,{method:"POST"});
    const data=await response.json();if(!response.ok)throw new Error(data.error||"更新できませんでした。");
    updateTitle.textContent="更新を適用します";updateMessage.textContent=data.message+"\nこの画面は自動的に開き直します。";
  }catch(error){updateTitle.textContent="更新を中止しました";updateMessage.textContent=error.message;installUpdateButton.disabled=false;}
};
