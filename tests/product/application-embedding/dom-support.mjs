/** Small DOM contract double. NOT evidence of browser layout or browser security. */
export class Element {
 constructor(doc,tag){Object.assign(this,{ownerDocument:doc,tagName:tag,children:[],attrs:{},dataset:{},_text:'',value:'',disabled:false,checked:false});}
 set textContent(v){this._text=v;this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
 setAttribute(k,v){this.attrs[k]=v;}append(...v){this.children.push(...v);}replaceChildren(...v){this._text='';this.children=v;}
 addEventListener(k,f){(this.events??={})[k]=f;}focus(){}setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;}
 close(){this.open=false;}showModal(){this.open=true;}
}
export class Document{createElement(t){return new Element(this,t);}}
export const find=(root,fn)=>fn(root)?root:root.children.map(x=>find(x,fn)).find(Boolean);
