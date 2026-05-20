import{f as ve,h as u,v as M,I as Ft,J as Ut,K as We,L as qt,d as lt,a as xe,M as A,b as a,N as dt,e as h,O as F,P as Xt,Q as Kt,R as Yt,u as ct,g as je,j as bt,k as ee,S as Q,T as Jt,t as Qt,i as ut,U as Zt,F as re,V as ea,W as ta,X as aa,Y as ra,Z as Oe,$ as Ve,o as pt,a0 as na,a1 as oa,G as ia,a2 as sa,a3 as la,a4 as Ge,a5 as Te,a6 as da,a7 as ca,a8 as oe,m as E,p as T,w as L,q as S,x as B,r as I,a9 as ba,y as G,C as ce,A as ye,B as Ye,z as P,D as ua,_ as pa}from"./index-pHRDPS5a.js";import{r as Je,c as Le,a as ue,u as fa,B as ie,b as we,N as ke}from"./http-L27XDz7k.js";import{c as va,b as Qe,f as Ae,u as Ue,A as ga,d as ha,o as ma,a as Ze,N as xa}from"./Card-BpxcKLiO.js";import{g as ya,N as wa}from"./Space-ChU3zCES.js";import{N as et}from"./Popconfirm-B6Fop3ol.js";const Ca=Qe(".v-x-scroll",{overflow:"auto",scrollbarWidth:"none"},[Qe("&::-webkit-scrollbar",{width:0,height:0})]),Sa=ve({name:"XScroll",props:{disabled:Boolean,onScroll:Function},setup(){const e=M(null);function t(d){!(d.currentTarget.offsetWidth<d.currentTarget.scrollWidth)||d.deltaY===0||(d.currentTarget.scrollLeft+=d.deltaY+d.deltaX,d.preventDefault())}const i=Ft();return Ca.mount({id:"vueuc/x-scroll",head:!0,anchorMetaName:va,ssr:i}),Object.assign({selfRef:e,handleWheel:t},{scrollTo(...d){var _;(_=e.value)===null||_===void 0||_.scrollTo(...d)}})},render(){return u("div",{ref:"selfRef",onScroll:this.onScroll,onWheel:this.disabled?void 0:this.handleWheel,class:"v-x-scroll"},this.$slots)}});function tt(e,t="default",i=[]){const{children:p}=e;if(p!==null&&typeof p=="object"&&!Array.isArray(p)){const d=p[t];if(typeof d=="function")return d()}return i}var _a=/\s/;function $a(e){for(var t=e.length;t--&&_a.test(e.charAt(t)););return t}var za=/^\s+/;function Pa(e){return e&&e.slice(0,$a(e)+1).replace(za,"")}var at=NaN,Ra=/^[-+]0x[0-9a-f]+$/i,Ta=/^0b[01]+$/i,La=/^0o[0-7]+$/i,ka=parseInt;function rt(e){if(typeof e=="number")return e;if(Ut(e))return at;if(We(e)){var t=typeof e.valueOf=="function"?e.valueOf():e;e=We(t)?t+"":t}if(typeof e!="string")return e===0?e:+e;e=Pa(e);var i=Ta.test(e);return i||La.test(e)?ka(e.slice(2),i?2:8):Ra.test(e)?at:+e}var De=function(){return qt.Date.now()},Ba="Expected a function",Aa=Math.max,Wa=Math.min;function ja(e,t,i){var p,d,_,C,g,m,x=0,v=!1,l=!1,W=!0;if(typeof e!="function")throw new TypeError(Ba);t=rt(t)||0,We(i)&&(v=!!i.leading,l="maxWait"in i,_=l?Aa(rt(i.maxWait)||0,t):_,W="trailing"in i?!!i.trailing:W);function z(f){var V=p,Y=d;return p=d=void 0,x=f,C=e.apply(Y,V),C}function R(f){return x=f,g=setTimeout(O,t),v?z(f):C}function j(f){var V=f-m,Y=f-x,X=t-V;return l?Wa(X,_-Y):X}function k(f){var V=f-m,Y=f-x;return m===void 0||V>=t||V<0||l&&Y>=_}function O(){var f=De();if(k(f))return y(f);g=setTimeout(O,j(f))}function y(f){return g=void 0,W&&p?z(f):(p=d=void 0,C)}function U(){g!==void 0&&clearTimeout(g),x=0,p=m=d=g=void 0}function D(){return g===void 0?C:y(De())}function w(){var f=De(),V=k(f);if(p=arguments,d=this,m=f,V){if(g===void 0)return R(m);if(l)return clearTimeout(g),g=setTimeout(O,t),z(m)}return g===void 0&&(g=setTimeout(O,t)),C}return w.cancel=U,w.flush=D,w}var Ma="Expected a function";function Ha(e,t,i){var p=!0,d=!0;if(typeof e!="function")throw new TypeError(Ma);return We(i)&&(p="leading"in i?!!i.leading:p,d="trailing"in i?!!i.trailing:d),ja(e,t,{leading:p,maxWait:t,trailing:d})}const Ea={thPaddingBorderedSmall:"8px 12px",thPaddingBorderedMedium:"12px 16px",thPaddingBorderedLarge:"16px 24px",thPaddingSmall:"0",thPaddingMedium:"0",thPaddingLarge:"0",tdPaddingBorderedSmall:"8px 12px",tdPaddingBorderedMedium:"12px 16px",tdPaddingBorderedLarge:"16px 24px",tdPaddingSmall:"0 0 8px 0",tdPaddingMedium:"0 0 12px 0",tdPaddingLarge:"0 0 16px 0"};function Ia(e){const{tableHeaderColor:t,textColor2:i,textColor1:p,cardColor:d,modalColor:_,popoverColor:C,dividerColor:g,borderRadius:m,fontWeightStrong:x,lineHeight:v,fontSizeSmall:l,fontSizeMedium:W,fontSizeLarge:z}=e;return Object.assign(Object.assign({},Ea),{lineHeight:v,fontSizeSmall:l,fontSizeMedium:W,fontSizeLarge:z,titleTextColor:p,thColor:xe(d,t),thColorModal:xe(_,t),thColorPopover:xe(C,t),thTextColor:p,thFontWeight:x,tdTextColor:i,tdColor:d,tdColorModal:_,tdColorPopover:C,borderColor:xe(d,g),borderColorModal:xe(_,g),borderColorPopover:xe(C,g),borderRadius:m})}const Oa={common:lt,self:Ia},Va=A([a("descriptions",{fontSize:"var(--n-font-size)"},[a("descriptions-separator",`
 display: inline-block;
 margin: 0 8px 0 2px;
 `),a("descriptions-table-wrapper",[a("descriptions-table",[a("descriptions-table-row",[a("descriptions-table-header",{padding:"var(--n-th-padding)"}),a("descriptions-table-content",{padding:"var(--n-td-padding)"})])])]),dt("bordered",[a("descriptions-table-wrapper",[a("descriptions-table",[a("descriptions-table-row",[A("&:last-child",[a("descriptions-table-content",{paddingBottom:0})])])])])]),h("left-label-placement",[a("descriptions-table-content",[A("> *",{verticalAlign:"top"})])]),h("left-label-align",[A("th",{textAlign:"left"})]),h("center-label-align",[A("th",{textAlign:"center"})]),h("right-label-align",[A("th",{textAlign:"right"})]),h("bordered",[a("descriptions-table-wrapper",`
 border-radius: var(--n-border-radius);
 overflow: hidden;
 background: var(--n-merged-td-color);
 border: 1px solid var(--n-merged-border-color);
 `,[a("descriptions-table",[a("descriptions-table-row",[A("&:not(:last-child)",[a("descriptions-table-content",{borderBottom:"1px solid var(--n-merged-border-color)"}),a("descriptions-table-header",{borderBottom:"1px solid var(--n-merged-border-color)"})]),a("descriptions-table-header",`
 font-weight: 400;
 background-clip: padding-box;
 background-color: var(--n-merged-th-color);
 `,[A("&:not(:last-child)",{borderRight:"1px solid var(--n-merged-border-color)"})]),a("descriptions-table-content",[A("&:not(:last-child)",{borderRight:"1px solid var(--n-merged-border-color)"})])])])])]),a("descriptions-header",`
 font-weight: var(--n-th-font-weight);
 font-size: 18px;
 transition: color .3s var(--n-bezier);
 line-height: var(--n-line-height);
 margin-bottom: 16px;
 color: var(--n-title-text-color);
 `),a("descriptions-table-wrapper",`
 transition:
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `,[a("descriptions-table",`
 width: 100%;
 border-collapse: separate;
 border-spacing: 0;
 box-sizing: border-box;
 `,[a("descriptions-table-row",`
 box-sizing: border-box;
 transition: border-color .3s var(--n-bezier);
 `,[a("descriptions-table-header",`
 font-weight: var(--n-th-font-weight);
 line-height: var(--n-line-height);
 display: table-cell;
 box-sizing: border-box;
 color: var(--n-th-text-color);
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `),a("descriptions-table-content",`
 vertical-align: top;
 line-height: var(--n-line-height);
 display: table-cell;
 box-sizing: border-box;
 color: var(--n-td-text-color);
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `,[F("content",`
 transition: color .3s var(--n-bezier);
 display: inline-block;
 color: var(--n-td-text-color);
 `)]),F("label",`
 font-weight: var(--n-th-font-weight);
 transition: color .3s var(--n-bezier);
 display: inline-block;
 margin-right: 14px;
 color: var(--n-th-text-color);
 `)])])])]),a("descriptions-table-wrapper",`
 --n-merged-th-color: var(--n-th-color);
 --n-merged-td-color: var(--n-td-color);
 --n-merged-border-color: var(--n-border-color);
 `),Xt(a("descriptions-table-wrapper",`
 --n-merged-th-color: var(--n-th-color-modal);
 --n-merged-td-color: var(--n-td-color-modal);
 --n-merged-border-color: var(--n-border-color-modal);
 `)),Kt(a("descriptions-table-wrapper",`
 --n-merged-th-color: var(--n-th-color-popover);
 --n-merged-td-color: var(--n-td-color-popover);
 --n-merged-border-color: var(--n-border-color-popover);
 `))]),ft="DESCRIPTION_ITEM_FLAG";function Ga(e){return typeof e=="object"&&e&&!Array.isArray(e)?e.type&&e.type[ft]:!1}const Da=Object.assign(Object.assign({},je.props),{title:String,column:{type:Number,default:3},columns:Number,labelPlacement:{type:String,default:"top"},labelAlign:{type:String,default:"left"},separator:{type:String,default:":"},size:String,bordered:Boolean,labelClass:String,labelStyle:[Object,String],contentClass:String,contentStyle:[Object,String]}),Na=ve({name:"Descriptions",props:Da,slots:Object,setup(e){const{mergedClsPrefixRef:t,inlineThemeDisabled:i,mergedComponentPropsRef:p}=ct(e),d=ee(()=>{var m,x;return e.size||((x=(m=p==null?void 0:p.value)===null||m===void 0?void 0:m.Descriptions)===null||x===void 0?void 0:x.size)||"medium"}),_=je("Descriptions","-descriptions",Va,Oa,e,t),C=ee(()=>{const{bordered:m}=e,x=d.value,{common:{cubicBezierEaseInOut:v},self:{titleTextColor:l,thColor:W,thColorModal:z,thColorPopover:R,thTextColor:j,thFontWeight:k,tdTextColor:O,tdColor:y,tdColorModal:U,tdColorPopover:D,borderColor:w,borderColorModal:f,borderColorPopover:V,borderRadius:Y,lineHeight:X,[Q("fontSize",x)]:se,[Q(m?"thPaddingBordered":"thPadding",x)]:le,[Q(m?"tdPaddingBordered":"tdPadding",x)]:ne}}=_.value;return{"--n-title-text-color":l,"--n-th-padding":le,"--n-td-padding":ne,"--n-font-size":se,"--n-bezier":v,"--n-th-font-weight":k,"--n-line-height":X,"--n-th-text-color":j,"--n-td-text-color":O,"--n-th-color":W,"--n-th-color-modal":z,"--n-th-color-popover":R,"--n-td-color":y,"--n-td-color-modal":U,"--n-td-color-popover":D,"--n-border-radius":Y,"--n-border-color":w,"--n-border-color-modal":f,"--n-border-color-popover":V}}),g=i?bt("descriptions",ee(()=>{let m="";const{bordered:x}=e;return x&&(m+="a"),m+=d.value[0],m}),C,e):void 0;return{mergedClsPrefix:t,cssVars:i?void 0:C,themeClass:g==null?void 0:g.themeClass,onRender:g==null?void 0:g.onRender,compitableColumn:Ue(e,["columns","column"]),inlineThemeDisabled:i,mergedSize:d}},render(){const e=this.$slots.default,t=e?Ae(e()):[];t.length;const{contentClass:i,labelClass:p,compitableColumn:d,labelPlacement:_,labelAlign:C,mergedSize:g,bordered:m,title:x,cssVars:v,mergedClsPrefix:l,separator:W,onRender:z}=this;z==null||z();const R=t.filter(y=>Ga(y)),j={span:0,row:[],secondRow:[],rows:[]},O=R.reduce((y,U,D)=>{const w=U.props||{},f=R.length-1===D,V=["label"in w?w.label:tt(U,"label")],Y=[tt(U)],X=w.span||1,se=y.span;y.span+=X;const le=w.labelStyle||w["label-style"]||this.labelStyle,ne=w.contentStyle||w["content-style"]||this.contentStyle;if(_==="left")m?y.row.push(u("th",{class:[`${l}-descriptions-table-header`,p],colspan:1,style:le},V),u("td",{class:[`${l}-descriptions-table-content`,i],colspan:f?(d-se)*2+1:X*2-1,style:ne},Y)):y.row.push(u("td",{class:`${l}-descriptions-table-content`,colspan:f?(d-se)*2:X*2},u("span",{class:[`${l}-descriptions-table-content__label`,p],style:le},[...V,W&&u("span",{class:`${l}-descriptions-separator`},W)]),u("span",{class:[`${l}-descriptions-table-content__content`,i],style:ne},Y)));else{const de=f?(d-se)*2:X*2;y.row.push(u("th",{class:[`${l}-descriptions-table-header`,p],colspan:de,style:le},V)),y.secondRow.push(u("td",{class:[`${l}-descriptions-table-content`,i],colspan:de,style:ne},Y))}return(y.span>=d||f)&&(y.span=0,y.row.length&&(y.rows.push(y.row),y.row=[]),_!=="left"&&y.secondRow.length&&(y.rows.push(y.secondRow),y.secondRow=[])),y},j).rows.map(y=>u("tr",{class:`${l}-descriptions-table-row`},y));return u("div",{style:v,class:[`${l}-descriptions`,this.themeClass,`${l}-descriptions--${_}-label-placement`,`${l}-descriptions--${C}-label-align`,`${l}-descriptions--${g}-size`,m&&`${l}-descriptions--bordered`]},x||this.$slots.header?u("div",{class:`${l}-descriptions-header`},x||ya(this,"header")):null,u("div",{class:`${l}-descriptions-table-wrapper`},u("table",{class:`${l}-descriptions-table`},u("tbody",null,_==="top"&&u("tr",{class:`${l}-descriptions-table-row`,style:{visibility:"collapse"}},Yt(d*2,u("td",null))),O))))}}),Fa={label:String,span:{type:Number,default:1},labelClass:String,labelStyle:[Object,String],contentClass:String,contentStyle:[Object,String]},fe=ve({name:"DescriptionsItem",[ft]:!0,props:Fa,slots:Object,render(){return null}}),Ua={tabFontSizeSmall:"14px",tabFontSizeMedium:"14px",tabFontSizeLarge:"16px",tabGapSmallLine:"36px",tabGapMediumLine:"36px",tabGapLargeLine:"36px",tabGapSmallLineVertical:"8px",tabGapMediumLineVertical:"8px",tabGapLargeLineVertical:"8px",tabPaddingSmallLine:"6px 0",tabPaddingMediumLine:"10px 0",tabPaddingLargeLine:"14px 0",tabPaddingVerticalSmallLine:"6px 12px",tabPaddingVerticalMediumLine:"8px 16px",tabPaddingVerticalLargeLine:"10px 20px",tabGapSmallBar:"36px",tabGapMediumBar:"36px",tabGapLargeBar:"36px",tabGapSmallBarVertical:"8px",tabGapMediumBarVertical:"8px",tabGapLargeBarVertical:"8px",tabPaddingSmallBar:"4px 0",tabPaddingMediumBar:"6px 0",tabPaddingLargeBar:"10px 0",tabPaddingVerticalSmallBar:"6px 12px",tabPaddingVerticalMediumBar:"8px 16px",tabPaddingVerticalLargeBar:"10px 20px",tabGapSmallCard:"4px",tabGapMediumCard:"4px",tabGapLargeCard:"4px",tabGapSmallCardVertical:"4px",tabGapMediumCardVertical:"4px",tabGapLargeCardVertical:"4px",tabPaddingSmallCard:"8px 16px",tabPaddingMediumCard:"10px 20px",tabPaddingLargeCard:"12px 24px",tabPaddingSmallSegment:"4px 0",tabPaddingMediumSegment:"6px 0",tabPaddingLargeSegment:"8px 0",tabPaddingVerticalLargeSegment:"0 8px",tabPaddingVerticalSmallCard:"8px 12px",tabPaddingVerticalMediumCard:"10px 16px",tabPaddingVerticalLargeCard:"12px 20px",tabPaddingVerticalSmallSegment:"0 4px",tabPaddingVerticalMediumSegment:"0 6px",tabGapSmallSegment:"0",tabGapMediumSegment:"0",tabGapLargeSegment:"0",tabGapSmallSegmentVertical:"0",tabGapMediumSegmentVertical:"0",tabGapLargeSegmentVertical:"0",panePaddingSmall:"8px 0 0 0",panePaddingMedium:"12px 0 0 0",panePaddingLarge:"16px 0 0 0",closeSize:"18px",closeIconSize:"14px"};function qa(e){const{textColor2:t,primaryColor:i,textColorDisabled:p,closeIconColor:d,closeIconColorHover:_,closeIconColorPressed:C,closeColorHover:g,closeColorPressed:m,tabColor:x,baseColor:v,dividerColor:l,fontWeight:W,textColor1:z,borderRadius:R,fontSize:j,fontWeightStrong:k}=e;return Object.assign(Object.assign({},Ua),{colorSegment:x,tabFontSizeCard:j,tabTextColorLine:z,tabTextColorActiveLine:i,tabTextColorHoverLine:i,tabTextColorDisabledLine:p,tabTextColorSegment:z,tabTextColorActiveSegment:t,tabTextColorHoverSegment:t,tabTextColorDisabledSegment:p,tabTextColorBar:z,tabTextColorActiveBar:i,tabTextColorHoverBar:i,tabTextColorDisabledBar:p,tabTextColorCard:z,tabTextColorHoverCard:z,tabTextColorActiveCard:i,tabTextColorDisabledCard:p,barColor:i,closeIconColor:d,closeIconColorHover:_,closeIconColorPressed:C,closeColorHover:g,closeColorPressed:m,closeBorderRadius:R,tabColor:x,tabColorSegment:v,tabBorderColor:l,tabFontWeightActive:W,tabFontWeight:W,tabBorderRadius:R,paneTextColor:t,fontWeightStrong:k})}const Xa={common:lt,self:qa},Xe=Jt("n-tabs"),vt={tab:[String,Number,Object,Function],name:{type:[String,Number],required:!0},disabled:Boolean,displayDirective:{type:String,default:"if"},closable:{type:Boolean,default:void 0},tabProps:Object,label:[String,Number,Object,Function]},Be=ve({__TAB_PANE__:!0,name:"TabPane",alias:["TabPanel"],props:vt,slots:Object,setup(e){const t=ut(Xe,null);return t||Qt("tab-pane","`n-tab-pane` must be placed inside `n-tabs`."),{style:t.paneStyleRef,class:t.paneClassRef,mergedClsPrefix:t.mergedClsPrefixRef}},render(){return u("div",{class:[`${this.mergedClsPrefix}-tab-pane`,this.class],style:this.style},this.$slots)}}),Ka=Object.assign({internalLeftPadded:Boolean,internalAddable:Boolean,internalCreatedByPane:Boolean},ra(vt,["displayDirective"])),qe=ve({__TAB__:!0,inheritAttrs:!1,name:"Tab",props:Ka,setup(e){const{mergedClsPrefixRef:t,valueRef:i,typeRef:p,closableRef:d,tabStyleRef:_,addTabStyleRef:C,tabClassRef:g,addTabClassRef:m,tabChangeIdRef:x,onBeforeLeaveRef:v,triggerRef:l,handleAdd:W,activateTab:z,handleClose:R}=ut(Xe);return{trigger:l,mergedClosable:ee(()=>{if(e.internalAddable)return!1;const{closable:j}=e;return j===void 0?d.value:j}),style:_,addStyle:C,tabClass:g,addTabClass:m,clsPrefix:t,value:i,type:p,handleClose(j){j.stopPropagation(),!e.disabled&&R(e.name)},activateTab(){if(e.disabled)return;if(e.internalAddable){W();return}const{name:j}=e,k=++x.id;if(j!==i.value){const{value:O}=v;O?Promise.resolve(O(e.name,i.value)).then(y=>{y&&x.id===k&&z(j)}):z(j)}}}},render(){const{internalAddable:e,clsPrefix:t,name:i,disabled:p,label:d,tab:_,value:C,mergedClosable:g,trigger:m,$slots:{default:x}}=this,v=d??_;return u("div",{class:`${t}-tabs-tab-wrapper`},this.internalLeftPadded?u("div",{class:`${t}-tabs-tab-pad`}):null,u("div",Object.assign({key:i,"data-name":i,"data-disabled":p?!0:void 0},Zt({class:[`${t}-tabs-tab`,C===i&&`${t}-tabs-tab--active`,p&&`${t}-tabs-tab--disabled`,g&&`${t}-tabs-tab--closable`,e&&`${t}-tabs-tab--addable`,e?this.addTabClass:this.tabClass],onClick:m==="click"?this.activateTab:void 0,onMouseenter:m==="hover"?this.activateTab:void 0,style:e?this.addStyle:this.style},this.internalCreatedByPane?this.tabProps||{}:this.$attrs)),u("span",{class:`${t}-tabs-tab__label`},e?u(re,null,u("div",{class:`${t}-tabs-tab__height-placeholder`}," "),u(ea,{clsPrefix:t},{default:()=>u(ga,null)})):x?x():typeof v=="object"?v:ta(v??i)),g&&this.type==="card"?u(aa,{clsPrefix:t,class:`${t}-tabs-tab__close`,onClick:this.handleClose,disabled:p}):null))}}),Ya=a("tabs",`
 box-sizing: border-box;
 width: 100%;
 display: flex;
 flex-direction: column;
 transition:
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
`,[h("segment-type",[a("tabs-rail",[A("&.transition-disabled",[a("tabs-capsule",`
 transition: none;
 `)])])]),h("top",[a("tab-pane",`
 padding: var(--n-pane-padding-top) var(--n-pane-padding-right) var(--n-pane-padding-bottom) var(--n-pane-padding-left);
 `)]),h("left",[a("tab-pane",`
 padding: var(--n-pane-padding-right) var(--n-pane-padding-bottom) var(--n-pane-padding-left) var(--n-pane-padding-top);
 `)]),h("left, right",`
 flex-direction: row;
 `,[a("tabs-bar",`
 width: 2px;
 right: 0;
 transition:
 top .2s var(--n-bezier),
 max-height .2s var(--n-bezier),
 background-color .3s var(--n-bezier);
 `),a("tabs-tab",`
 padding: var(--n-tab-padding-vertical); 
 `)]),h("right",`
 flex-direction: row-reverse;
 `,[a("tab-pane",`
 padding: var(--n-pane-padding-left) var(--n-pane-padding-top) var(--n-pane-padding-right) var(--n-pane-padding-bottom);
 `),a("tabs-bar",`
 left: 0;
 `)]),h("bottom",`
 flex-direction: column-reverse;
 justify-content: flex-end;
 `,[a("tab-pane",`
 padding: var(--n-pane-padding-bottom) var(--n-pane-padding-right) var(--n-pane-padding-top) var(--n-pane-padding-left);
 `),a("tabs-bar",`
 top: 0;
 `)]),a("tabs-rail",`
 position: relative;
 padding: 3px;
 border-radius: var(--n-tab-border-radius);
 width: 100%;
 background-color: var(--n-color-segment);
 transition: background-color .3s var(--n-bezier);
 display: flex;
 align-items: center;
 `,[a("tabs-capsule",`
 border-radius: var(--n-tab-border-radius);
 position: absolute;
 pointer-events: none;
 background-color: var(--n-tab-color-segment);
 box-shadow: 0 1px 3px 0 rgba(0, 0, 0, .08);
 transition: transform 0.3s var(--n-bezier);
 `),a("tabs-tab-wrapper",`
 flex-basis: 0;
 flex-grow: 1;
 display: flex;
 align-items: center;
 justify-content: center;
 `,[a("tabs-tab",`
 overflow: hidden;
 border-radius: var(--n-tab-border-radius);
 width: 100%;
 display: flex;
 align-items: center;
 justify-content: center;
 `,[h("active",`
 font-weight: var(--n-font-weight-strong);
 color: var(--n-tab-text-color-active);
 `),A("&:hover",`
 color: var(--n-tab-text-color-hover);
 `)])])]),h("flex",[a("tabs-nav",`
 width: 100%;
 position: relative;
 `,[a("tabs-wrapper",`
 width: 100%;
 `,[a("tabs-tab",`
 margin-right: 0;
 `)])])]),a("tabs-nav",`
 box-sizing: border-box;
 line-height: 1.5;
 display: flex;
 transition: border-color .3s var(--n-bezier);
 `,[F("prefix, suffix",`
 display: flex;
 align-items: center;
 `),F("prefix","padding-right: 16px;"),F("suffix","padding-left: 16px;")]),h("top, bottom",[A(">",[a("tabs-nav",[a("tabs-nav-scroll-wrapper",[A("&::before",`
 top: 0;
 bottom: 0;
 left: 0;
 width: 20px;
 `),A("&::after",`
 top: 0;
 bottom: 0;
 right: 0;
 width: 20px;
 `),h("shadow-start",[A("&::before",`
 box-shadow: inset 10px 0 8px -8px rgba(0, 0, 0, .12);
 `)]),h("shadow-end",[A("&::after",`
 box-shadow: inset -10px 0 8px -8px rgba(0, 0, 0, .12);
 `)])])])])]),h("left, right",[a("tabs-nav-scroll-content",`
 flex-direction: column;
 `),A(">",[a("tabs-nav",[a("tabs-nav-scroll-wrapper",[A("&::before",`
 top: 0;
 left: 0;
 right: 0;
 height: 20px;
 `),A("&::after",`
 bottom: 0;
 left: 0;
 right: 0;
 height: 20px;
 `),h("shadow-start",[A("&::before",`
 box-shadow: inset 0 10px 8px -8px rgba(0, 0, 0, .12);
 `)]),h("shadow-end",[A("&::after",`
 box-shadow: inset 0 -10px 8px -8px rgba(0, 0, 0, .12);
 `)])])])])]),a("tabs-nav-scroll-wrapper",`
 flex: 1;
 position: relative;
 overflow: hidden;
 `,[a("tabs-nav-y-scroll",`
 height: 100%;
 width: 100%;
 overflow-y: auto; 
 scrollbar-width: none;
 `,[A("&::-webkit-scrollbar, &::-webkit-scrollbar-track-piece, &::-webkit-scrollbar-thumb",`
 width: 0;
 height: 0;
 display: none;
 `)]),A("&::before, &::after",`
 transition: box-shadow .3s var(--n-bezier);
 pointer-events: none;
 content: "";
 position: absolute;
 z-index: 1;
 `)]),a("tabs-nav-scroll-content",`
 display: flex;
 position: relative;
 min-width: 100%;
 min-height: 100%;
 width: fit-content;
 box-sizing: border-box;
 `),a("tabs-wrapper",`
 display: inline-flex;
 flex-wrap: nowrap;
 position: relative;
 `),a("tabs-tab-wrapper",`
 display: flex;
 flex-wrap: nowrap;
 flex-shrink: 0;
 flex-grow: 0;
 `),a("tabs-tab",`
 cursor: pointer;
 white-space: nowrap;
 flex-wrap: nowrap;
 display: inline-flex;
 align-items: center;
 color: var(--n-tab-text-color);
 font-size: var(--n-tab-font-size);
 background-clip: padding-box;
 padding: var(--n-tab-padding);
 transition:
 box-shadow .3s var(--n-bezier),
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `,[h("disabled",{cursor:"not-allowed"}),F("close",`
 margin-left: 6px;
 transition:
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 `),F("label",`
 display: flex;
 align-items: center;
 z-index: 1;
 `)]),a("tabs-bar",`
 position: absolute;
 bottom: 0;
 height: 2px;
 border-radius: 1px;
 background-color: var(--n-bar-color);
 transition:
 left .2s var(--n-bezier),
 max-width .2s var(--n-bezier),
 opacity .3s var(--n-bezier),
 background-color .3s var(--n-bezier);
 `,[A("&.transition-disabled",`
 transition: none;
 `),h("disabled",`
 background-color: var(--n-tab-text-color-disabled)
 `)]),a("tabs-pane-wrapper",`
 position: relative;
 overflow: hidden;
 transition: max-height .2s var(--n-bezier);
 `),a("tab-pane",`
 color: var(--n-pane-text-color);
 width: 100%;
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 opacity .2s var(--n-bezier);
 left: 0;
 right: 0;
 top: 0;
 `,[A("&.next-transition-leave-active, &.prev-transition-leave-active, &.next-transition-enter-active, &.prev-transition-enter-active",`
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 transform .2s var(--n-bezier),
 opacity .2s var(--n-bezier);
 `),A("&.next-transition-leave-active, &.prev-transition-leave-active",`
 position: absolute;
 `),A("&.next-transition-enter-from, &.prev-transition-leave-to",`
 transform: translateX(32px);
 opacity: 0;
 `),A("&.next-transition-leave-to, &.prev-transition-enter-from",`
 transform: translateX(-32px);
 opacity: 0;
 `),A("&.next-transition-leave-from, &.next-transition-enter-to, &.prev-transition-leave-from, &.prev-transition-enter-to",`
 transform: translateX(0);
 opacity: 1;
 `)]),a("tabs-tab-pad",`
 box-sizing: border-box;
 width: var(--n-tab-gap);
 flex-grow: 0;
 flex-shrink: 0;
 `),h("line-type, bar-type",[a("tabs-tab",`
 font-weight: var(--n-tab-font-weight);
 box-sizing: border-box;
 vertical-align: bottom;
 `,[A("&:hover",{color:"var(--n-tab-text-color-hover)"}),h("active",`
 color: var(--n-tab-text-color-active);
 font-weight: var(--n-tab-font-weight-active);
 `),h("disabled",{color:"var(--n-tab-text-color-disabled)"})])]),a("tabs-nav",[h("line-type",[h("top",[F("prefix, suffix",`
 border-bottom: 1px solid var(--n-tab-border-color);
 `),a("tabs-nav-scroll-content",`
 border-bottom: 1px solid var(--n-tab-border-color);
 `),a("tabs-bar",`
 bottom: -1px;
 `)]),h("left",[F("prefix, suffix",`
 border-right: 1px solid var(--n-tab-border-color);
 `),a("tabs-nav-scroll-content",`
 border-right: 1px solid var(--n-tab-border-color);
 `),a("tabs-bar",`
 right: -1px;
 `)]),h("right",[F("prefix, suffix",`
 border-left: 1px solid var(--n-tab-border-color);
 `),a("tabs-nav-scroll-content",`
 border-left: 1px solid var(--n-tab-border-color);
 `),a("tabs-bar",`
 left: -1px;
 `)]),h("bottom",[F("prefix, suffix",`
 border-top: 1px solid var(--n-tab-border-color);
 `),a("tabs-nav-scroll-content",`
 border-top: 1px solid var(--n-tab-border-color);
 `),a("tabs-bar",`
 top: -1px;
 `)]),F("prefix, suffix",`
 transition: border-color .3s var(--n-bezier);
 `),a("tabs-nav-scroll-content",`
 transition: border-color .3s var(--n-bezier);
 `),a("tabs-bar",`
 border-radius: 0;
 `)]),h("card-type",[F("prefix, suffix",`
 transition: border-color .3s var(--n-bezier);
 `),a("tabs-pad",`
 flex-grow: 1;
 transition: border-color .3s var(--n-bezier);
 `),a("tabs-tab-pad",`
 transition: border-color .3s var(--n-bezier);
 `),a("tabs-tab",`
 font-weight: var(--n-tab-font-weight);
 border: 1px solid var(--n-tab-border-color);
 background-color: var(--n-tab-color);
 box-sizing: border-box;
 position: relative;
 vertical-align: bottom;
 display: flex;
 justify-content: space-between;
 font-size: var(--n-tab-font-size);
 color: var(--n-tab-text-color);
 `,[h("addable",`
 padding-left: 8px;
 padding-right: 8px;
 font-size: 16px;
 justify-content: center;
 `,[F("height-placeholder",`
 width: 0;
 font-size: var(--n-tab-font-size);
 `),dt("disabled",[A("&:hover",`
 color: var(--n-tab-text-color-hover);
 `)])]),h("closable","padding-right: 8px;"),h("active",`
 background-color: #0000;
 font-weight: var(--n-tab-font-weight-active);
 color: var(--n-tab-text-color-active);
 `),h("disabled","color: var(--n-tab-text-color-disabled);")])]),h("left, right",`
 flex-direction: column; 
 `,[F("prefix, suffix",`
 padding: var(--n-tab-padding-vertical);
 `),a("tabs-wrapper",`
 flex-direction: column;
 `),a("tabs-tab-wrapper",`
 flex-direction: column;
 `,[a("tabs-tab-pad",`
 height: var(--n-tab-gap-vertical);
 width: 100%;
 `)])]),h("top",[h("card-type",[a("tabs-scroll-padding","border-bottom: 1px solid var(--n-tab-border-color);"),F("prefix, suffix",`
 border-bottom: 1px solid var(--n-tab-border-color);
 `),a("tabs-tab",`
 border-top-left-radius: var(--n-tab-border-radius);
 border-top-right-radius: var(--n-tab-border-radius);
 `,[h("active",`
 border-bottom: 1px solid #0000;
 `)]),a("tabs-tab-pad",`
 border-bottom: 1px solid var(--n-tab-border-color);
 `),a("tabs-pad",`
 border-bottom: 1px solid var(--n-tab-border-color);
 `)])]),h("left",[h("card-type",[a("tabs-scroll-padding","border-right: 1px solid var(--n-tab-border-color);"),F("prefix, suffix",`
 border-right: 1px solid var(--n-tab-border-color);
 `),a("tabs-tab",`
 border-top-left-radius: var(--n-tab-border-radius);
 border-bottom-left-radius: var(--n-tab-border-radius);
 `,[h("active",`
 border-right: 1px solid #0000;
 `)]),a("tabs-tab-pad",`
 border-right: 1px solid var(--n-tab-border-color);
 `),a("tabs-pad",`
 border-right: 1px solid var(--n-tab-border-color);
 `)])]),h("right",[h("card-type",[a("tabs-scroll-padding","border-left: 1px solid var(--n-tab-border-color);"),F("prefix, suffix",`
 border-left: 1px solid var(--n-tab-border-color);
 `),a("tabs-tab",`
 border-top-right-radius: var(--n-tab-border-radius);
 border-bottom-right-radius: var(--n-tab-border-radius);
 `,[h("active",`
 border-left: 1px solid #0000;
 `)]),a("tabs-tab-pad",`
 border-left: 1px solid var(--n-tab-border-color);
 `),a("tabs-pad",`
 border-left: 1px solid var(--n-tab-border-color);
 `)])]),h("bottom",[h("card-type",[a("tabs-scroll-padding","border-top: 1px solid var(--n-tab-border-color);"),F("prefix, suffix",`
 border-top: 1px solid var(--n-tab-border-color);
 `),a("tabs-tab",`
 border-bottom-left-radius: var(--n-tab-border-radius);
 border-bottom-right-radius: var(--n-tab-border-radius);
 `,[h("active",`
 border-top: 1px solid #0000;
 `)]),a("tabs-tab-pad",`
 border-top: 1px solid var(--n-tab-border-color);
 `),a("tabs-pad",`
 border-top: 1px solid var(--n-tab-border-color);
 `)])])])]),Ne=Ha,Ja=Object.assign(Object.assign({},je.props),{value:[String,Number],defaultValue:[String,Number],trigger:{type:String,default:"click"},type:{type:String,default:"bar"},closable:Boolean,justifyContent:String,size:String,placement:{type:String,default:"top"},tabStyle:[String,Object],tabClass:String,addTabStyle:[String,Object],addTabClass:String,barWidth:Number,paneClass:String,paneStyle:[String,Object],paneWrapperClass:String,paneWrapperStyle:[String,Object],addable:[Boolean,Object],tabsPadding:{type:Number,default:0},animated:Boolean,onBeforeLeave:Function,onAdd:Function,"onUpdate:value":[Function,Array],onUpdateValue:[Function,Array],onClose:[Function,Array],labelSize:String,activeName:[String,Number],onActiveNameChange:[Function,Array]}),Qa=ve({name:"Tabs",props:Ja,slots:Object,setup(e,{slots:t}){var i,p,d,_;const{mergedClsPrefixRef:C,inlineThemeDisabled:g,mergedComponentPropsRef:m}=ct(e),x=je("Tabs","-tabs",Ya,Xa,e,C),v=M(null),l=M(null),W=M(null),z=M(null),R=M(null),j=M(null),k=M(!0),O=M(!0),y=Ue(e,["labelSize","size"]),U=ee(()=>{var r,n;if(y.value)return y.value;const b=(n=(r=m==null?void 0:m.value)===null||r===void 0?void 0:r.Tabs)===null||n===void 0?void 0:n.size;return b||"medium"}),D=Ue(e,["activeName","value"]),w=M((p=(i=D.value)!==null&&i!==void 0?i:e.defaultValue)!==null&&p!==void 0?p:t.default?(_=(d=Ae(t.default())[0])===null||d===void 0?void 0:d.props)===null||_===void 0?void 0:_.name:null),f=ha(D,w),V={id:0},Y=ee(()=>{if(!(!e.justifyContent||e.type==="card"))return{display:"flex",justifyContent:e.justifyContent}});Ve(f,()=>{V.id=0,de(),Z()});function X(){var r;const{value:n}=f;return n===null?null:(r=v.value)===null||r===void 0?void 0:r.querySelector(`[data-name="${n}"]`)}function se(r){if(e.type==="card")return;const{value:n}=l;if(!n)return;const b=n.style.opacity==="0";if(r){const $=`${C.value}-tabs-bar--disabled`,{barWidth:N,placement:te}=e;if(r.dataset.disabled==="true"?n.classList.add($):n.classList.remove($),["top","bottom"].includes(te)){if(ne(["top","maxHeight","height"]),typeof N=="number"&&r.offsetWidth>=N){const ae=Math.floor((r.offsetWidth-N)/2)+r.offsetLeft;n.style.left=`${ae}px`,n.style.maxWidth=`${N}px`}else n.style.left=`${r.offsetLeft}px`,n.style.maxWidth=`${r.offsetWidth}px`;n.style.width="8192px",b&&(n.style.transition="none"),n.offsetWidth,b&&(n.style.transition="",n.style.opacity="1")}else{if(ne(["left","maxWidth","width"]),typeof N=="number"&&r.offsetHeight>=N){const ae=Math.floor((r.offsetHeight-N)/2)+r.offsetTop;n.style.top=`${ae}px`,n.style.maxHeight=`${N}px`}else n.style.top=`${r.offsetTop}px`,n.style.maxHeight=`${r.offsetHeight}px`;n.style.height="8192px",b&&(n.style.transition="none"),n.offsetHeight,b&&(n.style.transition="",n.style.opacity="1")}}}function le(){if(e.type==="card")return;const{value:r}=l;r&&(r.style.opacity="0")}function ne(r){const{value:n}=l;if(n)for(const b of r)n.style[b]=""}function de(){if(e.type==="card")return;const r=X();r?se(r):le()}function Z(){var r;const n=(r=R.value)===null||r===void 0?void 0:r.$el;if(!n)return;const b=X();if(!b)return;const{scrollLeft:$,offsetWidth:N}=n,{offsetLeft:te,offsetWidth:ae}=b;$>te?n.scrollTo({top:0,left:te,behavior:"smooth"}):te+ae>$+N&&n.scrollTo({top:0,left:te+ae-N,behavior:"smooth"})}const J=M(null);let Ce=0,K=null;function Se(r){const n=J.value;if(n){Ce=r.getBoundingClientRect().height;const b=`${Ce}px`,$=()=>{n.style.height=b,n.style.maxHeight=b};K?($(),K(),K=null):K=$}}function _e(r){const n=J.value;if(n){const b=r.getBoundingClientRect().height,$=()=>{document.body.offsetHeight,n.style.maxHeight=`${b}px`,n.style.height=`${Math.max(Ce,b)}px`};K?(K(),K=null,$()):K=$}}function Me(){const r=J.value;if(r){r.style.maxHeight="",r.style.height="";const{paneWrapperStyle:n}=e;if(typeof n=="string")r.style.cssText=n;else if(n){const{maxHeight:b,height:$}=n;b!==void 0&&(r.style.maxHeight=b),$!==void 0&&(r.style.height=$)}}}const ze={value:[]},Pe=M("next");function He(r){const n=f.value;let b="next";for(const $ of ze.value){if($===n)break;if($===r){b="prev";break}}Pe.value=b,Ee(r)}function Ee(r){const{onActiveNameChange:n,onUpdateValue:b,"onUpdate:value":$}=e;n&&Le(n,r),b&&Le(b,r),$&&Le($,r),w.value=r}function o(r){const{onClose:n}=e;n&&Le(n,r)}function s(){const{value:r}=l;if(!r)return;const n="transition-disabled";r.classList.add(n),de(),r.classList.remove(n)}const c=M(null);function H({transitionDisabled:r}){const n=v.value;if(!n)return;r&&n.classList.add("transition-disabled");const b=X();b&&c.value&&(c.value.style.width=`${b.offsetWidth}px`,c.value.style.height=`${b.offsetHeight}px`,c.value.style.transform=`translateX(${b.offsetLeft-oa(getComputedStyle(n).paddingLeft)}px)`,r&&c.value.offsetWidth),r&&n.classList.remove("transition-disabled")}Ve([f],()=>{e.type==="segment"&&Ge(()=>{H({transitionDisabled:!1})})}),pt(()=>{e.type==="segment"&&H({transitionDisabled:!0})});let q=0;function be(r){var n;if(r.contentRect.width===0&&r.contentRect.height===0||q===r.contentRect.width)return;q=r.contentRect.width;const{type:b}=e;if((b==="line"||b==="bar")&&s(),b!=="segment"){const{placement:$}=e;Ie(($==="top"||$==="bottom"?(n=R.value)===null||n===void 0?void 0:n.$el:j.value)||null)}}const pe=Ne(be,64);Ve([()=>e.justifyContent,()=>e.size],()=>{Ge(()=>{const{type:r}=e;(r==="line"||r==="bar")&&s()})});const ge=M(!1);function gt(r){var n;const{target:b,contentRect:{width:$,height:N}}=r,te=b.parentElement.parentElement.offsetWidth,ae=b.parentElement.parentElement.offsetHeight,{placement:me}=e;if(!ge.value)me==="top"||me==="bottom"?te<$&&(ge.value=!0):ae<N&&(ge.value=!0);else{const{value:$e}=z;if(!$e)return;me==="top"||me==="bottom"?te-$>$e.$el.offsetWidth&&(ge.value=!1):ae-N>$e.$el.offsetHeight&&(ge.value=!1)}Ie(((n=R.value)===null||n===void 0?void 0:n.$el)||null)}const ht=Ne(gt,64);function mt(){const{onAdd:r}=e;r&&r(),Ge(()=>{const n=X(),{value:b}=R;!n||!b||b.scrollTo({left:n.offsetLeft,top:0,behavior:"smooth"})})}function Ie(r){if(!r)return;const{placement:n}=e;if(n==="top"||n==="bottom"){const{scrollLeft:b,scrollWidth:$,offsetWidth:N}=r;k.value=b<=0,O.value=b+N>=$}else{const{scrollTop:b,scrollHeight:$,offsetHeight:N}=r;k.value=b<=0,O.value=b+N>=$}}const xt=Ne(r=>{Ie(r.target)},64);ca(Xe,{triggerRef:oe(e,"trigger"),tabStyleRef:oe(e,"tabStyle"),tabClassRef:oe(e,"tabClass"),addTabStyleRef:oe(e,"addTabStyle"),addTabClassRef:oe(e,"addTabClass"),paneClassRef:oe(e,"paneClass"),paneStyleRef:oe(e,"paneStyle"),mergedClsPrefixRef:C,typeRef:oe(e,"type"),closableRef:oe(e,"closable"),valueRef:f,tabChangeIdRef:V,onBeforeLeaveRef:oe(e,"onBeforeLeave"),activateTab:He,handleClose:o,handleAdd:mt}),ma(()=>{de(),Z()}),na(()=>{const{value:r}=W;if(!r)return;const{value:n}=C,b=`${n}-tabs-nav-scroll-wrapper--shadow-start`,$=`${n}-tabs-nav-scroll-wrapper--shadow-end`;k.value?r.classList.remove(b):r.classList.add(b),O.value?r.classList.remove($):r.classList.add($)});const yt={syncBarPosition:()=>{de()}},wt=()=>{H({transitionDisabled:!0})},Ke=ee(()=>{const{value:r}=U,{type:n}=e,b={card:"Card",bar:"Bar",line:"Line",segment:"Segment"}[n],$=`${r}${b}`,{self:{barColor:N,closeIconColor:te,closeIconColorHover:ae,closeIconColorPressed:me,tabColor:$e,tabBorderColor:Ct,paneTextColor:St,tabFontWeight:_t,tabBorderRadius:$t,tabFontWeightActive:zt,colorSegment:Pt,fontWeightStrong:Rt,tabColorSegment:Tt,closeSize:Lt,closeIconSize:kt,closeColorHover:Bt,closeColorPressed:At,closeBorderRadius:Wt,[Q("panePadding",r)]:Re,[Q("tabPadding",$)]:jt,[Q("tabPaddingVertical",$)]:Mt,[Q("tabGap",$)]:Ht,[Q("tabGap",`${$}Vertical`)]:Et,[Q("tabTextColor",n)]:It,[Q("tabTextColorActive",n)]:Ot,[Q("tabTextColorHover",n)]:Vt,[Q("tabTextColorDisabled",n)]:Gt,[Q("tabFontSize",r)]:Dt},common:{cubicBezierEaseInOut:Nt}}=x.value;return{"--n-bezier":Nt,"--n-color-segment":Pt,"--n-bar-color":N,"--n-tab-font-size":Dt,"--n-tab-text-color":It,"--n-tab-text-color-active":Ot,"--n-tab-text-color-disabled":Gt,"--n-tab-text-color-hover":Vt,"--n-pane-text-color":St,"--n-tab-border-color":Ct,"--n-tab-border-radius":$t,"--n-close-size":Lt,"--n-close-icon-size":kt,"--n-close-color-hover":Bt,"--n-close-color-pressed":At,"--n-close-border-radius":Wt,"--n-close-icon-color":te,"--n-close-icon-color-hover":ae,"--n-close-icon-color-pressed":me,"--n-tab-color":$e,"--n-tab-font-weight":_t,"--n-tab-font-weight-active":zt,"--n-tab-padding":jt,"--n-tab-padding-vertical":Mt,"--n-tab-gap":Ht,"--n-tab-gap-vertical":Et,"--n-pane-padding-left":Te(Re,"left"),"--n-pane-padding-right":Te(Re,"right"),"--n-pane-padding-top":Te(Re,"top"),"--n-pane-padding-bottom":Te(Re,"bottom"),"--n-font-weight-strong":Rt,"--n-tab-color-segment":Tt}}),he=g?bt("tabs",ee(()=>`${U.value[0]}${e.type[0]}`),Ke,e):void 0;return Object.assign({mergedClsPrefix:C,mergedValue:f,renderedNames:new Set,segmentCapsuleElRef:c,tabsPaneWrapperRef:J,tabsElRef:v,barElRef:l,addTabInstRef:z,xScrollInstRef:R,scrollWrapperElRef:W,addTabFixed:ge,tabWrapperStyle:Y,handleNavResize:pe,mergedSize:U,handleScroll:xt,handleTabsResize:ht,cssVars:g?void 0:Ke,themeClass:he==null?void 0:he.themeClass,animationDirection:Pe,renderNameListRef:ze,yScrollElRef:j,handleSegmentResize:wt,onAnimationBeforeLeave:Se,onAnimationEnter:_e,onAnimationAfterEnter:Me,onRender:he==null?void 0:he.onRender},yt)},render(){const{mergedClsPrefix:e,type:t,placement:i,addTabFixed:p,addable:d,mergedSize:_,renderNameListRef:C,onRender:g,paneWrapperClass:m,paneWrapperStyle:x,$slots:{default:v,prefix:l,suffix:W}}=this;g==null||g();const z=v?Ae(v()).filter(w=>w.type.__TAB_PANE__===!0):[],R=v?Ae(v()).filter(w=>w.type.__TAB__===!0):[],j=!R.length,k=t==="card",O=t==="segment",y=!k&&!O&&this.justifyContent;C.value=[];const U=()=>{const w=u("div",{style:this.tabWrapperStyle,class:`${e}-tabs-wrapper`},y?null:u("div",{class:`${e}-tabs-scroll-padding`,style:i==="top"||i==="bottom"?{width:`${this.tabsPadding}px`}:{height:`${this.tabsPadding}px`}}),j?z.map((f,V)=>(C.value.push(f.props.name),Fe(u(qe,Object.assign({},f.props,{internalCreatedByPane:!0,internalLeftPadded:V!==0&&(!y||y==="center"||y==="start"||y==="end")}),f.children?{default:f.children.tab}:void 0)))):R.map((f,V)=>(C.value.push(f.props.name),Fe(V!==0&&!y?it(f):f))),!p&&d&&k?ot(d,(j?z.length:R.length)!==0):null,y?null:u("div",{class:`${e}-tabs-scroll-padding`,style:{width:`${this.tabsPadding}px`}}));return u("div",{ref:"tabsElRef",class:`${e}-tabs-nav-scroll-content`},k&&d?u(Oe,{onResize:this.handleTabsResize},{default:()=>w}):w,k?u("div",{class:`${e}-tabs-pad`}):null,k?null:u("div",{ref:"barElRef",class:`${e}-tabs-bar`}))},D=O?"top":i;return u("div",{class:[`${e}-tabs`,this.themeClass,`${e}-tabs--${t}-type`,`${e}-tabs--${_}-size`,y&&`${e}-tabs--flex`,`${e}-tabs--${D}`],style:this.cssVars},u("div",{class:[`${e}-tabs-nav--${t}-type`,`${e}-tabs-nav--${D}`,`${e}-tabs-nav`]},Je(l,w=>w&&u("div",{class:`${e}-tabs-nav__prefix`},w)),O?u(Oe,{onResize:this.handleSegmentResize},{default:()=>u("div",{class:`${e}-tabs-rail`,ref:"tabsElRef"},u("div",{class:`${e}-tabs-capsule`,ref:"segmentCapsuleElRef"},u("div",{class:`${e}-tabs-wrapper`},u("div",{class:`${e}-tabs-tab`}))),j?z.map((w,f)=>(C.value.push(w.props.name),u(qe,Object.assign({},w.props,{internalCreatedByPane:!0,internalLeftPadded:f!==0}),w.children?{default:w.children.tab}:void 0))):R.map((w,f)=>(C.value.push(w.props.name),f===0?w:it(w))))}):u(Oe,{onResize:this.handleNavResize},{default:()=>u("div",{class:`${e}-tabs-nav-scroll-wrapper`,ref:"scrollWrapperElRef"},["top","bottom"].includes(D)?u(Sa,{ref:"xScrollInstRef",onScroll:this.handleScroll},{default:U}):u("div",{class:`${e}-tabs-nav-y-scroll`,onScroll:this.handleScroll,ref:"yScrollElRef"},U()))}),p&&d&&k?ot(d,!0):null,Je(W,w=>w&&u("div",{class:`${e}-tabs-nav__suffix`},w))),j&&(this.animated&&(D==="top"||D==="bottom")?u("div",{ref:"tabsPaneWrapperRef",style:x,class:[`${e}-tabs-pane-wrapper`,m]},nt(z,this.mergedValue,this.renderedNames,this.onAnimationBeforeLeave,this.onAnimationEnter,this.onAnimationAfterEnter,this.animationDirection)):nt(z,this.mergedValue,this.renderedNames)))}});function nt(e,t,i,p,d,_,C){const g=[];return e.forEach(m=>{const{name:x,displayDirective:v,"display-directive":l}=m.props,W=R=>v===R||l===R,z=t===x;if(m.key!==void 0&&(m.key=x),z||W("show")||W("show:lazy")&&i.has(x)){i.has(x)||i.add(x);const R=!W("if");g.push(R?ia(m,[[da,z]]):m)}}),C?u(sa,{name:`${C}-transition`,onBeforeLeave:p,onEnter:d,onAfterEnter:_},{default:()=>g}):g}function ot(e,t){return u(qe,{ref:"addTabInstRef",key:"__addable",name:"__addable",internalCreatedByPane:!0,internalAddable:!0,internalLeftPadded:t,disabled:typeof e=="object"&&e.disabled})}function it(e){const t=la(e);return t.props?t.props.internalLeftPadded=!0:t.props={internalLeftPadded:!0},t}function Fe(e){return Array.isArray(e.dynamicProps)?e.dynamicProps.includes("internalLeftPadded")||e.dynamicProps.push("internalLeftPadded"):e.dynamicProps=["internalLeftPadded"],e}async function Za(e={}){const{data:t}=await ue.get("/api/gateway/sessions",{params:e});return t}async function er(e,t={}){const{data:i}=await ue.get(`/api/gateway/sessions/${encodeURIComponent(e)}`,{params:t});return i}async function tr(e){const{data:t}=await ue.delete(`/api/gateway/sessions/${encodeURIComponent(e)}`,{data:{confirm:e}});return t}async function ar(){const{data:e}=await ue.post("/api/gateway/prune");return e}async function rr(){const{data:e}=await ue.post("/api/gateway/dedupe-messages");return e}async function nr(e){const{data:t}=await ue.get(`/api/gateway/sessions/${encodeURIComponent(e)}/export`);return t}async function or(e,t){const{data:i}=await ue.post(`/api/gateway/sessions/${encodeURIComponent(e)}/heartbeats`,{content:t});return i}async function st(e,t){const{data:i}=await ue.delete(`/api/gateway/sessions/${encodeURIComponent(e)}/heartbeats`,{data:t});return i}const ir={class:"sessions-page"},sr={class:"toolbar"},lr={class:"thread-strip"},dr=["onClick"],cr={key:0,class:"stack"},br={class:"mini-list"},ur={key:0,class:"stack"},pr={class:"mini-list"},fr={key:0,class:"stack"},vr={class:"meta-line"},gr={class:"mini-list"},hr={class:"heartbeat-editor"},mr={class:"heartbeat-actions"},xr={key:0,class:"chat-list"},yr={class:"chat-head"},wr={class:"chat-body"},Cr={key:0,class:"load-more-row"},Sr={class:"danger-zone"},_r=ve({__name:"SessionsView",setup(e){const t=fa(),i=M(!1),p=M(!1),d=M(!1),_=M(!1),C=M(!1),g=M(""),m=M(""),x=M([]),v=M(""),l=M(null),W=M(""),z=M(!1),R=M(!1),j=M(100),k=ee(()=>{var o;return((o=l.value)==null?void 0:o.session)||x.value.find(s=>s.session_tag===v.value)}),O=ee(()=>{var o;return((o=l.value)==null?void 0:o.heartbeats)||[]}),y=ee(()=>O.value.slice(0,j.value)),U=ee(()=>Math.max(O.value.length-y.value.length,0));pt(D);async function D(){i.value=!0;try{const o=await Za({limit:200,q:m.value.trim()});x.value=o.sessions,!v.value&&o.sessions.length?await w(o.sessions[0].session_tag):v.value&&!o.sessions.some(s=>s.session_tag===v.value)?(v.value="",l.value=null):v.value&&await w(v.value)}catch(o){t.error(Z(o,"加载线程列表失败"))}finally{i.value=!1}}async function w(o){v.value=o,await f(o)}async function f(o){p.value=!0,j.value=100;try{l.value=await er(o)}catch(s){l.value=null,t.error(Z(s,"加载线程详情失败"))}finally{p.value=!1}}async function V(o){g.value=o;try{await tr(o),t.success(`已删除线程：${o}`),v.value===o&&(v.value="",l.value=null),await D()}catch(s){t.error(Z(s,"删除失败"))}finally{g.value=""}}async function Y(){_.value=!0;try{const o=await rr(),s=(o==null?void 0:o.deleted)||{};t.success(`已去重：消息 ${s.gateway_messages||0} 条，原始窗口 ${s.raw_request_windows||0} 个`),await D()}catch(o){t.error(Z(o,"去重失败"))}finally{_.value=!1}}async function X(){d.value=!0;try{const o=await ar(),s=(o==null?void 0:o.deleted)||{};t.success(`已清理：消息 ${s.gateway_messages||0}，快照 ${s.request_context_snapshots||0}，原始窗口 ${s.raw_request_windows||0}`),await D()}catch(o){t.error(Z(o,"清理失败"))}finally{d.value=!1}}async function se(){if(v.value){z.value=!0;try{await or(v.value,W.value),W.value="",t.success("Heartbeat 已写入"),await f(v.value)}catch(o){t.error(Z(o,"Heartbeat 写入失败"))}finally{z.value=!1}}}async function le(o){if(v.value){R.value=!0;try{await st(v.value,{ids:[o]}),t.success("已删除 heartbeat"),await f(v.value)}catch(s){t.error(Z(s,"Heartbeat 删除失败"))}finally{R.value=!1}}}async function ne(){if(v.value){R.value=!0;try{await st(v.value,{delete_all:!0,confirm:"GLOBAL"}),t.success("已清空全局 heartbeat"),await f(v.value)}catch(o){t.error(Z(o,"Heartbeat 批量删除失败"))}finally{R.value=!1}}}async function de(o){C.value=!0;try{const s=await nr(o),c=new Date().toISOString().replace(/[:.]/g,"-"),H=o.replace(/[^\w.-]+/g,"_")||"session",q=new Blob([JSON.stringify(s,null,2)],{type:"application/json;charset=utf-8"}),be=URL.createObjectURL(q),pe=document.createElement("a");pe.href=be,pe.download=`shenyu-session-${H}-${c}.json`,document.body.appendChild(pe),pe.click(),pe.remove(),URL.revokeObjectURL(be),t.success(`已导出线程：${o}`)}catch(s){t.error(Z(s,"导出失败"))}finally{C.value=!1}}function Z(o,s){var H,q;const c=o;return((q=(H=c==null?void 0:c.response)==null?void 0:H.data)==null?void 0:q.detail)||(c==null?void 0:c.message)||s}function J(o){if(!o)return"-";const s=new Date(o);return Number.isNaN(s.getTime())?o:s.toLocaleString()}function Ce(o){return typeof o=="string"?o:Array.isArray(o)?o.map(s=>typeof s=="string"?s:s&&typeof s=="object"&&"text"in s?String(s.text||""):"").filter(Boolean).join(`
`):o==null?"":String(o)}function K(o,s=120){const c=Ce(o).trim();return c?c.length>s?`${c.slice(0,s-1).trim()}...`:c:"(空)"}function Se(o){return o==="user"?"圆圆":o==="assistant"?"沈予":o==="tool"?"工具":o==="system"?"系统":o||"未知"}function _e(o){return o==="user"?"info":o==="assistant"?"success":o==="tool"?"warning":"default"}function Me(o){return o.injected_at?`已注入 ${J(o.injected_at)}`:"待注入"}function ze(o){return`${J(o.created_at)} / ${o.message_count} 条 / 最新圆圆：${K(o.latest_user_text,80)}`}function Pe(o){return`${J(o.created_at)} / ${o.message_count} 条 / 最新圆圆：${K(o.latest_user_text,80)}`}function He(o){return`${J(o.created_at)} / ${o.reason} / ${o.injected_count}/${o.max_injections}`}function Ee(){j.value+=100}return(o,s)=>(B(),E("main",ir,[T(S(wa),{vertical:"",size:"medium"},{default:L(()=>[I("div",sr,[T(S(Ze),{value:m.value,"onUpdate:value":s[0]||(s[0]=c=>m.value=c),placeholder:"搜索线程标识或客户端名称",clearable:"",class:"search-input",onKeyup:ba(D,["enter"])},null,8,["value"]),T(S(ie),{type:"primary",loading:i.value,onClick:D},{default:L(()=>[...s[4]||(s[4]=[G("搜索",-1)])]),_:1},8,["loading"]),T(S(ie),{loading:i.value,onClick:D},{default:L(()=>[...s[5]||(s[5]=[G("刷新",-1)])]),_:1},8,["loading"]),T(S(ie),{loading:_.value,onClick:Y},{default:L(()=>[...s[6]||(s[6]=[G("一键清除重复消息",-1)])]),_:1},8,["loading"]),T(S(ie),{loading:d.value,onClick:X},{default:L(()=>[...s[7]||(s[7]=[G("按保留策略清理",-1)])]),_:1},8,["loading"])]),I("section",lr,[(B(!0),E(re,null,ce(x.value,c=>(B(),E("button",{key:c.session_tag,class:ua(["thread-chip",{active:v.value===c.session_tag}]),onClick:H=>w(c.session_tag)},[I("strong",null,P(c.session_tag),1),I("span",null,"原始 "+P(c.raw_request_window_count||0)+" / 快照 "+P(c.context_snapshot_count||0)+" / hb "+P(c.heartbeat_count||0),1),I("em",null,P(K(c.latest_user_text,90)),1)],10,dr))),128)),!x.value.length&&!i.value?(B(),ye(S(we),{key:0,description:"暂无线程"})):Ye("",!0)]),T(S(xa),{title:"线程详情",size:"small",loading:p.value},{default:L(()=>[k.value&&l.value?(B(),E(re,{key:0},[T(S(Na),{column:2,size:"small","label-placement":"left",bordered:""},{default:L(()=>[T(S(fe),{label:"线程标识"},{default:L(()=>[G(P(k.value.session_tag),1)]),_:1}),T(S(fe),{label:"客户端"},{default:L(()=>[G(P(k.value.client_name||"unknown"),1)]),_:1}),T(S(fe),{label:"开始时间"},{default:L(()=>[G(P(J(k.value.started_at)),1)]),_:1}),T(S(fe),{label:"最后活跃"},{default:L(()=>[G(P(J(k.value.last_active_at)),1)]),_:1}),T(S(fe),{label:"原始请求窗口"},{default:L(()=>[G(P(l.value.stats.raw_request_windows||0),1)]),_:1}),T(S(fe),{label:"缓存层"},{default:L(()=>[G(P(l.value.stats.heartbeats)+" heartbeat / "+P(l.value.stats.context_snapshots||0)+" snapshots / "+P(l.value.stats.raw_request_windows||0)+" raw / "+P(l.value.stats.cold_start_snapshots)+" cold start ",1)]),_:1}),T(S(fe),{label:"最新圆圆消息",span:2},{default:L(()=>[G(P(K(k.value.latest_user_text,220)),1)]),_:1})]),_:1}),T(S(Qa),{type:"line",animated:"",class:"detail-tabs"},{default:L(()=>[T(S(Be),{name:"raw-windows",tab:"消息"},{default:L(()=>{var c;return[(c=l.value.raw_request_windows)!=null&&c.length?(B(),E("div",cr,[(B(!0),E(re,null,ce(l.value.raw_request_windows,H=>(B(),E("section",{key:H.id,class:"block"},[I("h3",null,P(Pe(H)),1),I("div",br,[(B(!0),E(re,null,ce(H.messages,(q,be)=>(B(),E("div",{key:be,class:"mini-row"},[T(S(ke),{size:"small",type:_e(String(q.role||""))},{default:L(()=>[G(P(Se(String(q.role||""))),1)]),_:2},1032,["type"]),I("span",null,P(K(q.content,260)),1)]))),128))])]))),128))])):(B(),ye(S(we),{key:1,description:"暂无原始请求窗口"}))]}),_:1}),T(S(Be),{name:"snapshots",tab:"上下文快照"},{default:L(()=>[l.value.context_snapshots.length?(B(),E("div",ur,[(B(!0),E(re,null,ce(l.value.context_snapshots,c=>(B(),E("section",{key:c.id,class:"block"},[I("h3",null,P(ze(c)),1),I("div",pr,[(B(!0),E(re,null,ce(c.messages.slice(-8),(H,q)=>(B(),E("div",{key:q,class:"mini-row"},[T(S(ke),{size:"small",type:_e(String(H.role||""))},{default:L(()=>[G(P(Se(String(H.role||""))),1)]),_:2},1032,["type"]),I("span",null,P(K(H.content,240)),1)]))),128))])]))),128))])):(B(),ye(S(we),{key:1,description:"暂无上下文快照"}))]),_:1}),T(S(Be),{name:"cold-start",tab:"冷启动"},{default:L(()=>[l.value.cold_start_snapshots.length?(B(),E("div",fr,[(B(!0),E(re,null,ce(l.value.cold_start_snapshots,c=>(B(),E("section",{key:c.id,class:"block"},[I("h3",null,P(He(c)),1),I("div",vr," 来源线程："+P(c.source_session_tags.join(", ")||"-")+" / 来源消息："+P(c.source_message_count),1),(B(!0),E(re,null,ce(c.sources,H=>(B(),E("div",{key:`${c.id}-${H.session_tag}-${H.snapshot_at}`,class:"source-box"},[I("strong",null,P(H.session_tag||"unknown"),1),I("span",null,P(H.client_name||"unknown")+" / "+P(J(H.snapshot_at)),1),I("div",gr,[(B(!0),E(re,null,ce((H.messages||[]).slice(-6),(q,be)=>(B(),E("div",{key:be,class:"mini-row"},[T(S(ke),{size:"small",type:_e(String(q.role||""))},{default:L(()=>[G(P(Se(String(q.role||""))),1)]),_:2},1032,["type"]),I("span",null,P(K(q.content,220)),1)]))),128))])]))),128))]))),128))])):(B(),ye(S(we),{key:1,description:"暂无冷启动快照"}))]),_:1}),T(S(Be),{name:"heartbeats",tab:"Heartbeat"},{default:L(()=>[I("div",hr,[T(S(Ze),{value:W.value,"onUpdate:value":s[1]||(s[1]=c=>W.value=c),type:"textarea",placeholder:"写给沈予自己的 heartbeat。只写正文，不需要标签。",autosize:{minRows:4,maxRows:8}},null,8,["value"]),I("div",mr,[T(S(ie),{type:"primary",loading:z.value,onClick:se},{default:L(()=>[...s[8]||(s[8]=[G("写入 Heartbeat",-1)])]),_:1},8,["loading"]),T(S(et),{"positive-text":"清空","negative-text":"取消",onPositiveClick:ne},{trigger:L(()=>[T(S(ie),{type:"error",loading:R.value},{default:L(()=>[...s[9]||(s[9]=[G("清空全局 Heartbeat",-1)])]),_:1},8,["loading"])]),default:L(()=>[s[10]||(s[10]=G(" 清空全局 heartbeat？这个操作不会删除消息或上下文快照。 ",-1))]),_:1})])]),O.value.length?(B(),E("div",xr,[(B(!0),E(re,null,ce(y.value,c=>(B(),E("div",{key:c.id,class:"chat-row heartbeat-row"},[I("div",yr,[T(S(ke),{size:"small",type:"warning"},{default:L(()=>[...s[11]||(s[11]=[G("Heartbeat",-1)])]),_:1}),I("span",null,P(J(c.created_at)),1),I("span",null,P(Me(c)),1),T(S(ie),{size:"tiny",quaternary:"",type:"error",loading:R.value,onClick:H=>le(c.id)},{default:L(()=>[...s[12]||(s[12]=[G("删除",-1)])]),_:1},8,["loading","onClick"])]),I("div",wr,P(c.content),1)]))),128)),U.value?(B(),E("div",Cr,[T(S(ie),{secondary:"",onClick:Ee},{default:L(()=>[G("继续显示 "+P(Math.min(U.value,100))+" 条 / 剩余 "+P(U.value)+" 条",1)]),_:1})])):Ye("",!0)])):(B(),ye(S(we),{key:1,description:"暂无 heartbeat"}))]),_:1})]),_:1}),I("div",Sr,[T(S(ie),{loading:C.value,onClick:s[2]||(s[2]=c=>de(k.value.session_tag))},{default:L(()=>[...s[13]||(s[13]=[G(" 导出此线程 JSON ",-1)])]),_:1},8,["loading"]),T(S(et),{"positive-text":"删除","negative-text":"取消",onPositiveClick:s[3]||(s[3]=c=>V(k.value.session_tag))},{trigger:L(()=>[T(S(ie),{type:"error",loading:g.value===k.value.session_tag},{default:L(()=>[...s[14]||(s[14]=[G(" 删除此线程 ",-1)])]),_:1},8,["loading"])]),default:L(()=>[G(" 删除 "+P(k.value.session_tag)+" 及其所有相关本地 SQLite 数据。 ",1)]),_:1})])],64)):(B(),ye(S(we),{key:1,description:"请选择一个线程"}))]),_:1},8,["loading"])]),_:1})]))}}),Lr=pa(_r,[["__scopeId","data-v-dd7aadd0"]]);export{Lr as default};
