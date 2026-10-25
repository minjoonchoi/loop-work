/* Local Markdown subset. Never parses supplied HTML or assigns innerHTML. */
(function(global){'use strict';
const rawBlocks=new WeakMap(),renderedBlocks=new WeakMap();
const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
function safeURL(input){const s=String(input||'').trim();if(!s||/[\u0000-\u0020\u007f]/.test(s)||s.startsWith('//')||s.includes('\\'))return null;const scheme=/^([a-z][a-z\d+.-]*):/i.exec(s);if(scheme&&!['https','http','mailto'].includes(scheme[1].toLowerCase()))return null;return s;}
function readLink(text,start){if(text[start]!=='[')return null;let at=start+1,label='',brackets=0;const code=/(`+)([^\n]*?)\1/y;for(;at<text.length;at++){const c=text[at];if(c==='\n'||c==='\r')return null;if(c==='\\'&&at+1<text.length){label+=c+text[++at];continue;}if(c==='`'){code.lastIndex=at;const literal=code.exec(text);if(literal){label+=literal[0];at=code.lastIndex-1;continue;}}if(c==='[')brackets++;if(c===']'){if(!brackets)break;brackets--;}label+=c;}if(!label||text.slice(at,at+2)!=='](')return null;let destination='',nested=0;for(at+=2;at<text.length;at++){const c=text[at];if(/\s/.test(c))return null;if(c==='\\'&&at+1<text.length&&'\\()'.includes(text[at+1])){destination+=text[++at];continue;}if(c==='('){nested++;destination+=c;continue;}if(c===')'){if(nested){nested--;destination+=c;continue;}return {label,destination,end:at+1,raw:text.slice(start,at+1)};}destination+=c;}return null;}
function inline(parent,text,depth=0,labelEscapes=false){if(depth>8){parent.append(document.createTextNode(text));return;}
// Delimiter runs from our serializer can close one mark and open another.
// Keep a small nesting stack instead of matching flat [^*]+ spans.
const frames=[{node:parent}],token=/(`+)([^\n]*?)\1|~~((?:\\.|[^~\n])+)~~/y;
const append=n=>frames[frames.length-1].node.append(n);
function firstClosingRun(start){let i=start;while(i<text.length){if(text[i]==='\\'&&i+1<text.length&&'\\*`~[]#<>+-.|'.includes(text[i+1])){i+=2;continue;}const link=readLink(text,i);if(link){i=link.end;continue;}token.lastIndex=i;const m=token.exec(text);if(m){i=token.lastIndex;continue;}if(text[i]==='*'){let end=i;while(text[end]==='*')end++;if(i>0&&!/\s/.test(text[i-1]))return end-i;i=end;}else i++;}return 0;}
let at=0;while(at<text.length){if(text[at]==='\\'&&at+1<text.length&&('\\*`~[]#<>+-.|'.includes(text[at+1])||labelEscapes&&'()'.includes(text[at+1]))){append(document.createTextNode(text[at+1]));at+=2;continue;}
const link=readLink(text,at);if(link){const url=safeURL(link.destination);let n;if(!url){n=el('span',link.raw);n.dataset.literal=link.raw;n.contentEditable='false';}else{n=el('a');n.href=url;n.setAttribute('target','_blank');n.setAttribute('rel','noopener noreferrer');inline(n,link.label,depth+1,true);}append(n);at=link.end;continue;}
token.lastIndex=at;const m=token.exec(text);if(m){let n;if(m[1])n=el('code',m[2]);else{n=el('s');inline(n,m[3],depth+1,labelEscapes);}append(n);at=token.lastIndex;continue;}
if(text[at]==='*'){let end=at;while(text[end]==='*')end++;let remaining=end-at;const closing=at>0&&!/\s/.test(text[at-1]),opening=end<text.length&&!/\s/.test(text[end]);
if(closing){while(frames.length>1&&remaining>=frames[frames.length-1].width){const frame=frames.pop();remaining-=frame.width;append(frame.node);}}
if(remaining&&opening&&frames.length+depth<8){let widths;if(remaining===3)widths=firstClosingRun(end)===2?[1,2]:[2,1];else if(remaining===1||remaining===2)widths=[remaining];else widths=[];
for(const width of widths){frames.push({node:el(width===2?'strong':'em'),width,start:end-remaining});remaining-=width;}}
if(remaining)append(document.createTextNode('*'.repeat(remaining)));at=end;continue;}
let end=at+1;while(end<text.length&&!['*','`','[','~','\\'].includes(text[end]))end++;append(document.createTextNode(text.slice(at,end)));at=end;}
// Incomplete/unsupported delimiter syntax remains literal, never supplied HTML.
if(frames.length>1){const first=frames[1];parent.append(document.createTextNode(text.slice(first.start)));}}

function blocks(source){const lines=source.match(/[^\n]*\n|[^\n]+$/g)||[];const out=[];let i=0;while(i<lines.length){let start=i,line=lines[i],type='paragraph';
if(/^\s*$/.test(line)){type='blank';i++;}
else if(/^ {0,3}(`{3,}|~{3,})/.test(line)){type='code';const fence=/^ {0,3}(`{3,}|~{3,})/.exec(line)[1];i++;while(i<lines.length&&!new RegExp('^ {0,3}'+fence[0]+'{'+fence.length+',}\\s*$').test(lines[i].replace(/\n$/,'')))i++;if(i<lines.length)i++;}
else if(/^#{1,6} /.test(line)){type='heading';i++;}
else if(/^> ?/.test(line)){type='quote';while(i<lines.length&&/^> ?/.test(lines[i]))i++;}
else if(/^(?:[-+*] |\d+\. )/.test(line)){type='list';while(i<lines.length&&/^(?:[-+*] |\d+\. |\s{2,}\S)/.test(lines[i]))i++;if(lines.slice(start,i).some(x=>/^\s{2,}\S/.test(x)))type='raw';}
else if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){type='table';i+=2;while(i<lines.length&&lines[i].includes('|')&&!/^\s*$/.test(lines[i]))i++;}
else{while(i<lines.length&&!/^\s*$/.test(lines[i])){if(i>start&&/^(#{1,6} |>|`{3,}|~{3,}|[-+*] |\d+\. )/.test(lines[i]))break;i++;}if(/^\s*</.test(line)||/^\s*(?:\[.+\]:|---\s*$|\$\$)/.test(line))type='raw';}
out.push({type,raw:lines.slice(start,i).join('')});}return out;}
function cellParts(line){return line.trim().replace(/^\|/,'').replace(/\|$/,'').split(/(?<!\\)\|/).map(x=>x.trim().replace(/\\\|/g,'|'));}
function renderBlock(block,editable=false){const text=block.raw.replace(/\n$/,'');let node;
if(block.type==='blank'){node=el('div');node.className='md-blank';node.append(el('br'));}
else if(block.type==='heading'){const m=/^(#{1,6}) (.*)$/s.exec(text);node=el('h'+m[1].length);inline(node,m[2]);}
else if(block.type==='code'){node=el('pre');const ls=text.split('\n'),f=/^ {0,3}(`{3,}|~{3,})([^\n]*)/.exec(ls[0]);const closed=ls.length>1&&new RegExp('^ {0,3}'+f[1][0]+'{'+f[1].length+',}\\s*$').test(ls[ls.length-1]);node.dataset.codeLanguage=f[2].trim();node.dataset.codeClosed=String(closed);node.append(el('code',ls.slice(1,closed?-1:undefined).join('\n')));}
else if(block.type==='quote'){node=el('blockquote');inline(node,text.split('\n').map(x=>x.replace(/^> ?/,'')).join('\n'));}
else if(block.type==='list'){node=el(/^\d/.test(text)?'ol':'ul');for(const line of text.split('\n')){const item=el('li'),content=line.replace(/^(?:[-+*]|\d+\.) /,'');const task=/^\[([ xX])\] (.*)$/.exec(content);if(task){const box=el('input');box.type='checkbox';box.checked=task[1].toLowerCase()==='x';box.disabled=!editable;box.contentEditable='false';box.setAttribute('aria-label','항목 완료');box.onchange=()=>{node.dataset.dirty='true';node.dispatchEvent(new Event('input',{bubbles:true}));};item.append(box);inline(item,task[2]);}else inline(item,content);node.append(item);}}
else if(block.type==='table'){node=el('table');const rows=text.split('\n');for(const [index,line]of rows.entries()){if(index===1)continue;const tr=el('tr');for(const cell of cellParts(line)){const td=el(index===0?'th':'td');inline(td,cell);tr.append(td);}node.append(tr);}}
else if(block.type==='raw'){node=el('pre',text);node.className='md-raw';node.contentEditable='false';node.setAttribute('aria-label','지원하지 않는 문법 · 원문 모드에서 편집');}
else{node=el('p');inline(node,text);}
node.dataset.mdBlock='true';rawBlocks.set(node,block.raw);renderedBlocks.set(node,node.innerHTML);return node;}
function render(source,target,{editable=false}={}){target.replaceChildren();for(const block of blocks(source))target.append(renderBlock(block,editable));if(editable&&!target.childNodes.length){const p=el('p');p.dataset.mdBlock='true';p.append(el('br'));rawBlocks.set(p,'');renderedBlocks.set(p,p.innerHTML);target.append(p);}return target;}
function inlineText(node,marks={}){if(node.nodeType===Node.TEXT_NODE)return marks.rawText?node.data:node.data.replace(/[\\*`~<[\]]/g,'\\$&');if(node.nodeType!==Node.ELEMENT_NODE)return '';if(node.dataset.literal!==undefined)return node.dataset.literal;if(node.tagName==='INPUT')return '';const strong=['STRONG','B'].includes(node.tagName),emphasis=['EM','I'].includes(node.tagName);const next={...marks,strong:marks.strong||strong,emphasis:marks.emphasis||emphasis,rawText:marks.rawText||node.tagName==='CODE'||node.tagName==='PRE',strike:marks.strike||['S','STRIKE','DEL'].includes(node.tagName)};const text=Array.from(node.childNodes,child=>inlineText(child,next)).join('');switch(node.tagName){case 'BR':return '\n';case 'DIV':return text+(node.dataset.mdBlock?'':'\n');case 'STRONG':case 'B':return marks.strong?text:'**'+text+'**';case 'EM':case 'I':return marks.emphasis?text:'*'+text+'*';case 'S':case 'STRIKE':case 'DEL':return marks.strike?text:'~~'+text+'~~';case 'CODE':{const fence='`'.repeat(Math.max(1,...Array.from(text.matchAll(/`+/g),x=>x[0].length+1)));return fence+text+fence;}case 'A':{const href=safeURL(node.getAttribute('href'));return href?'['+text+']('+href.replace(/[()]/g,'\\$&')+')':text;}default:return text;}}
function paragraphText(text){return text.replace(/^( {0,3})([#>+\-])/gm,'$1\\$2').replace(/^( {0,3}\d+)\.(?=\s)/gm,'$1\\.');}
function serializeBlock(node){if(node.nodeType===Node.TEXT_NODE)return paragraphText(inlineText(node));if(node.dataset.dirty!=='true'&&rawBlocks.has(node)&&renderedBlocks.get(node)===node.innerHTML)return rawBlocks.get(node);const tag=node.tagName,text=inlineText(node);if(node.classList.contains('md-raw'))return rawBlocks.get(node)||node.textContent;let result=text;
if(tag==='P'||tag==='DIV')result=paragraphText(text);
if(/^H[1-6]$/.test(tag))result='#'.repeat(Number(tag.slice(1)))+' '+text;
else if(tag==='PRE'){const literal=node.querySelector('code')?.textContent??node.textContent;const fence='`'.repeat(Math.max(3,...Array.from(literal.matchAll(/`+/g),x=>x[0].length+1)));result=fence+(node.dataset.codeLanguage||'')+'\n'+literal+'\n'+fence;}
else if(tag==='BLOCKQUOTE')result=text.split('\n').map(x=>'> '+x).join('\n');
else if(tag==='UL'||tag==='OL')result=Array.from(node.children,(li,i)=>{const box=li.querySelector('input[type=checkbox]');return (tag==='OL'?(i+1)+'. ':'- ')+(box?'['+(box.checked?'x':' ')+'] ':'')+inlineText(li);}).join('\n');
else if(tag==='TABLE'){const rows=Array.from(node.rows,tr=>Array.from(tr.cells,c=>inlineText(c).replace(/\|/g,'\\|').replace(/\n/g,' ')));if(rows.length)result='| '+rows[0].join(' | ')+' |\n| '+rows[0].map(()=>'---').join(' | ')+' |'+rows.slice(1).map(row=>'\n| '+row.join(' | ')+' |').join('');}
return result+'\n';}
function serialize(target){return Array.from(target.childNodes,n=>n.nodeType===Node.ELEMENT_NODE||n.nodeType===Node.TEXT_NODE?serializeBlock(n):n.textContent).join('');}
global.LoopMarkdown={safeURL,render,blocks,serialize,renderBlock,inlineText};
})(window);
