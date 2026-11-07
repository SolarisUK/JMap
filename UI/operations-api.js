/* The operations UI uses the same contract in bundled preview and HTTP API mode. */
(() => {
  'use strict';
  const clone = value => value === undefined ? undefined : structuredClone(value);
  class OperationsApi {
    constructor(options = {}) {
      const params = new URL(location.href).searchParams;
      const config = window.JMAP_OPERATIONS_CONFIG || {};
      this.mode = options.mode || params.get('mode') || config.mode || (options.baseUrl || params.get('api') || config.apiBase ? 'api' : 'bundled');
      this.baseUrl = (options.baseUrl || params.get('api') || config.apiBase || location.origin).replace(/\/$/, '');
      if (!['api', 'bundled'].includes(this.mode)) throw new Error('Data mode must be api or bundled.');
      this.bundle = window.JMAP_SIMULATION_STUBS;
      if (this.mode === 'bundled' && !this.bundle) throw new Error('Simulation bundle is unavailable. Start the local API or regenerate the stubs.');
      this.cache = new Map();
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
    reference() { return this.mode === 'bundled' ? Promise.resolve(clone(this.bundle.reference)) : this.request('/reference'); }
    zones() { return this.mode === 'bundled' ? Promise.resolve(clone(this.bundle.zones)) : this.request('/zones'); }
    edges() { return this.mode === 'bundled' ? Promise.resolve(clone(this.bundle.edges)) : this.request('/edges'); }
    scenarios() { return this.mode === 'bundled' ? Promise.resolve(clone(this.bundle.scenarios)) : this.request('/scenarios'); }
    async series(scenario, strategy) {
      if (this.mode !== 'bundled') return this.request(`/state/series?${new URLSearchParams({ scenario, strategy })}`);
      const result = this.bundle.series[scenario]?.[strategy];
      if (!result) throw new Error(`No bundled episode for ${scenario} / ${strategy}.`);
      return clone(result);
    }
    async state(scenario, strategy, timestamp, step) {
      if (this.mode !== 'bundled') return this.request(`/state?${new URLSearchParams({ scenario, strategy, t: timestamp })}`);
      const frames = this.bundle.states[scenario]?.[strategy];
      const result = frames?.find(frame => frame.timestamp_utc === timestamp) || frames?.[step];
      if (!result) throw new Error('The requested state is not in the generated episode.');
      return clone(result);
    }
    async compare(scenario) {
      if (this.mode !== 'bundled') return this.request(`/compare?${new URLSearchParams({ scenario })}`);
      const result = this.bundle.compare[scenario];
      if (!result) throw new Error('Comparison results are unavailable.');
      return clone(result);
    }
    async forecast(zone, issueTime) {
      if (this.mode !== 'bundled') return this.request(`/forecast/${encodeURIComponent(zone)}?${new URLSearchParams({ issue_time: issueTime })}`);
      const result = this.bundle.forecasts[zone];
      if (!result) throw new Error(`No bundled forecast for ${zone}.`);
      return clone(result);
    }
    incident(scenario, incident) {
      if (this.mode === 'bundled') throw new Error('Custom incident injection requires the API. Bundled preview provides the three pre-generated scenarios.');
      return this.request(`/incident?${new URLSearchParams({ scenario })}`, { method: 'POST', body: JSON.stringify(incident) });
    }
  }
  window.OperationsApi = OperationsApi;
})();
