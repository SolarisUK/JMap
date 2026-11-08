/* Operations values are read from the HTTP API at runtime. */
(() => {
  'use strict';
  class OperationsApi {
    constructor(options = {}) {
      const params = new URL(location.href).searchParams;
      const config = window.JMAP_OPERATIONS_CONFIG || {};
      this.mode = 'api';
      const local = location.protocol === 'file:' || ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
      const defaultBase = local ? 'http://127.0.0.1:8000' : location.origin;
      this.baseUrl = (options.baseUrl || params.get('api') || config.apiBase || defaultBase).replace(/\/$/, '');
    }
    async request(path, options = {}) {
      const response = await fetch(`${this.baseUrl}${path}`, { ...options, headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
      if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body); } catch {}
        throw new Error(message);
      }
      return response.json();
    }
    reference() { return this.request('/reference'); }
    zones() { return this.request('/zones'); }
    edges() { return this.request('/edges'); }
    scenarios() { return this.request('/scenarios'); }
    series(scenario, strategy) {
      return this.request(`/state/series?${new URLSearchParams({ scenario, strategy })}`);
    }
    state(scenario, strategy, timestamp) {
      return this.request(`/state?${new URLSearchParams({ scenario, strategy, t: timestamp })}`);
    }
    compare(scenario) { return this.request(`/compare?${new URLSearchParams({ scenario })}`); }
    forecast(zone, issueTime, scenario) {
      return this.request(`/forecast/${encodeURIComponent(zone)}?${new URLSearchParams({ issue_time: issueTime, ...(scenario ? { scenario } : {}) })}`);
    }
    incident(scenario, incident) {
      return this.request(`/incident?${new URLSearchParams({ scenario })}`, { method: 'POST', body: JSON.stringify(incident) });
    }
  }
  window.OperationsApi = OperationsApi;
})();
