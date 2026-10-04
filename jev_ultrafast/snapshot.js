(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>
        n.nodeType===3
          ? (n.parentElement && ['STYLE','SCRIPT','NOSCRIPT','TEMPLATE'].includes(n.parentElement.tagName) ? '' : n.textContent)
          : n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' && !['STYLE','SCRIPT','NOSCRIPT','TEMPLATE'].includes(n.tagName)
            ? name(n,seen)
            : ''
      ).join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  cache.pageKey=()=>[
    performance.timeOrigin,
    location.href,
    scrollX,
    scrollY,
    innerWidth,
    innerHeight
  ];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  const actions=[];
  for (const e of document.querySelectorAll(selector)) {
    if (!safe(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2, rname=role(e);
    if (!rname || r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const base={node:identity(e),role:rname,label:name(e)||rname,
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    // 暴露链接地址（截断）：搜索结果页要按 host 挑"官方站点"那一条（s001 实况：
    // 目标短语 "OpenAI" 出现在多条结果标题里，只看 label 挑不出 openai.com）。
    // javascript:/data:/# 一律不带，避免把 payload 撑爆。
    const _href=e.getAttribute('href')||'';
    if (_href && !/^(javascript:|data:|#)/i.test(_href)) base.href=_href.slice(0,120);
    // 结果卡片的显示域名（Google 的 <cite>）：新版结果链接是 /goto?url=CAES… 不透明编码，
    // 解不出真实地址，host 只能拿到 www.google.com；而结果卡片里的 cite 就是
    // "https://openai.com"。按域名挑"官方站点"这条判据只能靠它（s001 实况）。
    // 只走 3 层：走太远会把页眉/页脚的链接也认成"属于某个结果卡片"
    // （实测 e1"跳到主要内容"、e2"无障碍功能帮助"都被标成了 openai.com）。
    if (e.tagName==='A') {
      let s=e;
      for (let i=0; s&&i<3; i++, s=s.parentElement) {
        const c=s.querySelector&&s.querySelector('cite');
        if (c&&c.innerText) { base.site=c.innerText.trim().slice(0,80); break; }
      }
    }
    const _nm=e.getAttribute('name');
    if (_nm && _nm.length<=40) base.name=_nm;
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  // 日历日格补采：部分站点（Google Flights）把整块日期网格放在 aria-hidden 之下，
  // 日格是无 role 的 div，只有完整日期 aria-label——主 selector 收不到（无 role），
  // visible() 也会因 aria-hidden 祖先排除。但它们是唯一可交互的日期入口。
  // 单列一轮补进来：附在既有 action 之后，不改动原有顺序与编号。
  const dayRe=/^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}$/;
  const seenNodes=new Set(actions.map(a=>a.node));
  for (const e of document.querySelectorAll('div[aria-label],span[aria-label],td[aria-label]')) {
    const lab=(e.getAttribute('aria-label')||'').trim();
    if (!dayRe.test(lab)) continue;
    if (e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]')) continue;
    if (!e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) continue;
    if (getComputedStyle(e).pointerEvents==='none') continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
    if (r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
    const node=identity(e);
    if (seenNodes.has(node)) continue;
    seenNodes.add(node);
    actions.push({node,role:'gridcell',label:lab,kind:'click',value:'',
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}});
  }
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  // 稳定性 marker：**不含** text 与滚动位置，专供 Browser.fresh() 判"页面是否还是决策时
  // 那一张"。动态内容（时钟、广告、懒加载）会让 text 每帧都变 —— 用完整 marker 判会把
  // 每一次点击都判成 stale，形成"预测 → 拒绝 → 重预测"的活锁（n001/f002 实况：同一个
  // CLICK 决策连发 5 次、一次都没执行，最终被循环检测判 blocked）。滚动位置同理：
  // 页面自己滚动不代表内容变了。
  const marker_stable=[performance.timeOrigin,location.href,document.title];
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  // 一次滚到底 / 滚到顶：目标可能在视口外很远（自建站点 48 个条目的列表，560px 一步要滚
  // 十几次，模型实测滚 4~5 次就放弃 → "滚动到可见"类任务永远收不了口）。delta 取剩余高度。
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_bottom',kind:'scroll',
    label:'Scroll to bottom',delta:Math.max(0,Math.ceil(height-scrollY-innerHeight))});
  if (scrollY>0) actions.push({id:'scroll_top',kind:'scroll',label:'Scroll to top',delta:-Math.ceil(scrollY)});
  actions.push({id:'reload',kind:'reload',label:'Reload the page'});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height},actions,marker,marker_stable,page_key,guards,omitted_actions};
})()
