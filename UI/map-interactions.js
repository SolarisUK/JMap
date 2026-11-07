/* Map gestures must not start browser text selection or native drag ghosts.
 * Ordinary document text and editable fields retain normal selection behavior. */
(() => {
  'use strict';
  const surfaces = [...document.querySelectorAll('#generation-map,#transfer-map,#energy-map,#baseline-map,#response-map')];
  const active = new Map();
  function update() { document.body.classList.toggle('is-map-panning',[...active.values()].some(pointer=>pointer.moved)); }
  function release(event) { active.delete(event.pointerId); update(); }
  function cancel() { active.clear(); update(); }
  for (const surface of surfaces) {
    surface.dataset.mapSurface = '';
    surface.addEventListener('selectstart',event=>event.preventDefault());
    surface.addEventListener('dragstart',event=>event.preventDefault());
    surface.addEventListener('pointerdown',event=>{
      if (event.button !== 0) return;
      active.set(event.pointerId,{surface,x:event.clientX,y:event.clientY,moved:false});
    },true);
    surface.addEventListener('lostpointercapture',release);
  }
  document.addEventListener('pointermove',event=>{
    const pointer=active.get(event.pointerId); if(!pointer)return;
    if(Math.hypot(event.clientX-pointer.x,event.clientY-pointer.y)>4)pointer.moved=true;
    if(pointer.moved){
      const selection=window.getSelection();
      if(selection?.rangeCount&&(pointer.surface.contains(selection.anchorNode)||pointer.surface.contains(selection.focusNode)))selection.removeAllRanges();
    }
    update();
  },true);
  document.addEventListener('pointerup',release,true);
  document.addEventListener('pointercancel',release,true);
  window.addEventListener('blur',cancel);
  window.addEventListener('pagehide',cancel);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel();});
})();
