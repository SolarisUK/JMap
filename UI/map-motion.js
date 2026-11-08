/* Coordinated camera easing and directional markers. Motion never changes data. */
(() => {
  'use strict';
  const preference = () => matchMedia('(prefers-reduced-motion: reduce)');

  class Camera {
    constructor({ element, read, write, inverseZoom = true }) {
      this.element = element; this.read = read; this.write = write; this.inverseZoom = inverseZoom;
      this.media = preference(); this.frame = null; this.destination = null;
      this.interrupt = () => this.cancel();
      this.settle = () => { const target = this.destination; this.cancel(); if (target) this.write(target); };
      this.onPreference = () => { if (this.media.matches) this.settle(); };
      this.onVisibility = () => { if (document.hidden) this.settle(); };
      element.addEventListener('pointerdown', this.interrupt, true);
      this.media.addEventListener('change', this.onPreference);
      document.addEventListener('visibilitychange', this.onVisibility);
      window.addEventListener('pagehide', this.settle);
    }
    target() { return { ...(this.destination || this.read()) }; }
    wheelFactor(event, height) {
      const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1);
      const direction = Math.sign(pixels);
      // Reverse from the visible view, without first finishing the old zoom.
      if (direction && direction !== this.wheelDirection) this.destination = null;
      if (direction) this.wheelDirection = direction;
      return Math.exp(-Math.max(-120, Math.min(120, pixels)) * .002);
    }
    cancel() {
      if (this.frame !== null) cancelAnimationFrame(this.frame);
      this.frame = null; this.destination = null; this.wheelDirection = 0;
      delete this.element.dataset.cameraMoving;
    }
    to(target, { immediate = false } = {}) {
      const start = this.read();
      if (immediate || this.media.matches || document.hidden) { this.cancel(); this.write(target); return; }
      if (Object.keys(target).every(key => target[key] === start[key])) return;
      this.destination = { ...target }; this.element.dataset.cameraMoving = '';
      this.lastInput = performance.now();
      // Keep one animation alive across a wheel/trackpad burst. Restarting an
      // ease-out for every event repeatedly changes speed and delays fine input.
      if (this.frame !== null) return;
      let previous = this.lastInput;
      const step = now => {
        const target = this.destination, start = this.read();
        const eased = 1 - Math.exp(-Math.min(64, Math.max(0, now - previous)) / 55);
        previous = now;
        const value = {};
        for (const key of Object.keys(target)) {
          // Interpolating inverse zoom with world centres keeps the cursor's
          // geographic anchor fixed throughout the transition.
          value[key] = key === 'zoom' && this.inverseZoom
            ? 1 / (1 / start[key] + (1 / target[key] - 1 / start[key]) * eased)
            : start[key] + (target[key] - start[key]) * eased;
        }
        if (now - this.lastInput >= 400) { this.cancel(); this.write(target); }
        else { this.write(value); this.frame = requestAnimationFrame(step); }
      };
      this.frame = requestAnimationFrame(step);
    }
    destroy() {
      this.cancel(); this.element.removeEventListener('pointerdown', this.interrupt, true);
      this.media.removeEventListener('change', this.onPreference);
      document.removeEventListener('visibilitychange', this.onVisibility);
      window.removeEventListener('pagehide', this.settle);
    }
  }

  class Flow {
    constructor(element) {
      this.element = element; this.routes = []; this.enabled = true; this.visible = true;
      this.elapsed = 0; this.last = null; this.frame = null; this.suspended = false;
      this.media = preference(); this.sync = () => this.update();
      this.hide = () => { this.suspended = true; this.update(); };
      this.show = () => { this.suspended = false; this.update(); };
      this.media.addEventListener('change', this.sync);
      document.addEventListener('visibilitychange', this.sync);
      window.addEventListener('pagehide', this.hide); window.addEventListener('pageshow', this.show);
      this.observer = new IntersectionObserver(entries => { this.visible = entries[0].isIntersecting; this.update(); });
      this.observer.observe(element);
    }
    setRoutes(routes) { this.routes = routes; this.update(); }
    setEnabled(enabled) { this.enabled = enabled; this.update(); }
    moving() { return this.enabled && !this.media.matches && !document.hidden && this.visible && !this.suspended && this.routes.length > 0; }
    draw(moving) {
      for (const route of this.routes) {
        const { path, length, start = 0, end = length, scale = 1, reverse = false, markers } = route;
        const span = end - start;
        if (span <= 0) continue;
        for (const marker of markers) {
          // One shared, modest screen speed conveys direction, never MW or
          // electricity travel time. End fades make the loop unobtrusive.
          const distance = moving ? this.elapsed * .038 / scale * (reverse ? -1 : 1) : 0;
          const at = start + ((marker.at - start + distance) % span + span) % span;
          const point = path.getPointAtLength(at);
          const before = path.getPointAtLength(Math.max(0, at - .5 / scale));
          const after = path.getPointAtLength(Math.min(length, at + .5 / scale));
          const angle = Math.atan2(after.y - before.y, after.x - before.x) * 180 / Math.PI + (reverse ? 180 : 0);
          const fade = moving ? Math.min(1, (at - start) * scale / 16, (end - at) * scale / 16) : 1;
          marker.element.setAttribute('transform', `translate(${point.x} ${point.y}) rotate(${angle}) scale(${1 / scale})`);
          marker.element.setAttribute('opacity', route.obscured?.(point) ? 0 : fade);
        }
      }
    }
    update() {
      if (this.frame !== null) cancelAnimationFrame(this.frame);
      this.frame = null; this.last = null;
      const moving = this.moving(); this.draw(moving);
      this.element.toggleAttribute('data-flow-moving', moving);
      if (!moving) return;
      const step = now => {
        if (!this.moving()) { this.update(); return; }
        if (this.last !== null) this.elapsed += Math.min(64, now - this.last);
        this.last = now; this.draw(true); this.frame = requestAnimationFrame(step);
      };
      this.frame = requestAnimationFrame(step);
    }
    destroy() {
      if (this.frame !== null) cancelAnimationFrame(this.frame);
      this.observer.disconnect(); this.media.removeEventListener('change', this.sync);
      document.removeEventListener('visibilitychange', this.sync);
      window.removeEventListener('pagehide', this.hide); window.removeEventListener('pageshow', this.show);
      this.routes = [];
    }
  }
  window.JMapMotion = Object.freeze({ Camera, Flow });
})();
