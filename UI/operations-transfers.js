/* Directed corridor transfers, in MW. Positive flow follows topology from -> to.
 * These values describe network transfers, never generation or energy in MWh.
 * Selected-zone totals are unavailable if any connected active corridor has
 * unknown flow. Explicit zero current capacity means no available transfer.
 */
(function (root, factory) {
  'use strict';
  const api = Object.freeze(factory());
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JMapTransfers = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const IDLE_THRESHOLD_MW = .05;

  function record(value, label) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError(`${label} must be an object.`);
    return value;
  }
  function finiteOrUnknown(value, label, nonnegative = false) {
    if (value === null || value === undefined) return null;
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(`${label} must be a finite number or null.`);
    if (nonnegative && value < 0) throw new RangeError(`${label} cannot be negative.`);
    return value;
  }
  function add(total, value) {
    const result = total + value;
    if (!Number.isFinite(result)) throw new RangeError('Transfer totals exceed the supported numeric range.');
    return result;
  }

  function summarize(topologyEdges, snapshot, zoneId = null) {
    if (!Array.isArray(topologyEdges)) throw new TypeError('Topology edges must be an array.');
    if (snapshot !== null && snapshot !== undefined) record(snapshot, 'Snapshot');
    const measured = snapshot?.edges === null || snapshot?.edges === undefined ? {} : record(snapshot.edges, 'Snapshot edges');
    if (zoneId !== null && (typeof zoneId !== 'string' || !zoneId.trim())) throw new TypeError('Selected zone must be a nonempty string or null.');
    const seen = new Set();
    const rows = topologyEdges.map(edge => {
      record(edge, 'Topology edge');
      ['edge_id', 'from', 'to'].forEach(field => {
        if (typeof edge[field] !== 'string' || !edge[field].trim()) throw new TypeError(`Topology ${field} must be a nonempty string.`);
      });
      if (seen.has(edge.edge_id)) throw new RangeError(`Duplicate corridor ${edge.edge_id}.`);
      if (edge.from === edge.to) throw new RangeError(`Corridor ${edge.edge_id} must connect two different zones.`);
      seen.add(edge.edge_id);
      const observation = measured[edge.edge_id] === null || measured[edge.edge_id] === undefined ? {} : record(measured[edge.edge_id], `Snapshot edge ${edge.edge_id}`);
      const flowMw = finiteOrUnknown(observation.flow_mw, `${edge.edge_id}.flow_mw`);
      const limitMw = finiteOrUnknown(observation.limit_mw, `${edge.edge_id}.limit_mw`, true);
      const nameplateLimitMw = finiteOrUnknown(edge.limit_mw, `${edge.edge_id} nameplate limit`, true);
      const reportedLoading = finiteOrUnknown(observation.loading_frac, `${edge.edge_id}.loading_frac`, true);
      if (observation.tripped !== null && observation.tripped !== undefined && typeof observation.tripped !== 'boolean') throw new TypeError(`${edge.edge_id}.tripped must be boolean or null.`);
      const tripped = observation.tripped ?? null;
      const available = limitMw === null ? null : limitMw > 0;
      const known = flowMw !== null;
      const magnitudeMw = known ? Math.abs(flowMw) : null;
      const source = !known || flowMw === 0 ? null : flowMw < 0 ? edge.to : edge.from;
      const target = !known || flowMw === 0 ? null : flowMw < 0 ? edge.from : edge.to;
      // Preserve measured tiny flows for accounting; "idle" only suppresses
      // active-arrow/list rendering. Current zero capacity disables transfers.
      const effectiveMw = available === false ? 0 : magnitudeMw;
      const active = known && available !== false && magnitudeMw >= IDLE_THRESHOLD_MW;
      const loading = reportedLoading !== null ? reportedLoading : known && limitMw > 0 ? magnitudeMw / limitMw : null;
      if (loading !== null && !Number.isFinite(loading)) throw new RangeError(`${edge.edge_id} loading exceeds the supported numeric range.`);
      const status = available === false ? 'out'
        : loading !== null && loading > 1 + 1e-6 ? 'overloaded'
        : tripped === true ? 'tripped'
        : !known ? 'unknown'
        : magnitudeMw < IDLE_THRESHOLD_MW ? 'idle'
        : loading === null ? 'unknown'
        : loading >= .75 ? 'warning' : 'healthy';
      return {
        id: edge.edge_id, from: edge.from, to: edge.to, source, target,
        flowMw, magnitudeMw, effectiveMw, limitMw, nameplateLimitMw,
        loading, loadingSource: reportedLoading !== null ? 'reported' : loading !== null ? 'derived' : 'unknown',
        tripped, status, available, known, active,
        inconsistent: available === false && known && magnitudeMw > 0
      };
    });
    const zoneRows = zoneId === null ? [] : rows.filter(row => row.from === zoneId || row.to === zoneId);
    const zoneKnown = zoneRows.length > 0;
    const incomingRows = zoneRows.filter(row => row.active && row.target === zoneId);
    const outgoingRows = zoneRows.filter(row => row.active && row.source === zoneId);
    const incomplete = !zoneKnown || zoneRows.some(row => row.effectiveMw === null);
    const knownIncomingMw = zoneKnown ? zoneRows.filter(row => row.target === zoneId && row.effectiveMw !== null).reduce((total, row) => add(total, row.effectiveMw), 0) : null;
    const knownOutgoingMw = zoneKnown ? zoneRows.filter(row => row.source === zoneId && row.effectiveMw !== null).reduce((total, row) => add(total, row.effectiveMw), 0) : null;
    return {
      zoneId, rows, zoneRows, incomingRows, outgoingRows, incomplete,
      incomingMw: incomplete ? null : knownIncomingMw,
      outgoingMw: incomplete ? null : knownOutgoingMw,
      netImportMw: incomplete ? null : knownIncomingMw - knownOutgoingMw,
      knownIncomingMw, knownOutgoingMw,
      idleThresholdMw: IDLE_THRESHOLD_MW
    };
  }

  return { summarize };
});
