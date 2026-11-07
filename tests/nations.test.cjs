const test = require('node:test');
const assert = require('node:assert/strict');
const nations = require('../UI/assets/nations.js');
const official = require('../UI/assets/regions.js');

function contains([longitude, latitude], ring) {
  let inside = false;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const [ax, ay] = ring[i];
    const [bx, by] = ring[i + 1];
    if ((ay > latitude) !== (by > latitude) && longitude < (bx - ax) * (latitude - ay) / (by - ay) + ax) inside = !inside;
  }
  return inside;
}

test('nation geometry joins the four official annual records without missing or duplicate keys', () => {
  const keys = nations.features.map(feature => feature.key).sort();
  assert.deepEqual(keys, official.regions.map(region => region.key).sort());
  assert.equal(new Set(keys).size, 4);
  nations.features.forEach(feature => {
    assert.equal(feature.name, official.regions.find(region => region.key === feature.key).name);
    assert.ok(feature.polygons.length > 0);
  });
});

test('nation exteriors are closed nondegenerate finite WGS84 rings within the UK extent', () => {
  nations.features.forEach(feature => feature.polygons.forEach(ring => {
    assert.ok(ring.length >= 4, `${feature.name} ring needs three vertices and closure`);
    assert.deepEqual(ring[0], ring.at(-1), `${feature.name} ring must close`);
    assert.ok(new Set(ring.slice(0, -1).map(point => point.join(','))).size >= 3);
    ring.forEach(point => {
      assert.equal(point.length, 2);
      const [longitude, latitude] = point;
      assert.ok(Number.isFinite(longitude) && Number.isFinite(latitude));
      // Includes Rockall, west of the main UK viewport, and the Shetland Islands.
      assert.ok(longitude >= -14 && longitude <= 2, `${feature.name} longitude outside UK extent`);
      assert.ok(latitude >= 49 && latitude <= 61, `${feature.name} latitude outside UK extent`);
    });
  }));
});

test('each capital lies only within its corresponding nation, preventing swapped geometry keys', () => {
  const capitals = {
    england: [-0.1276, 51.5072],
    scotland: [-3.1883, 55.9533],
    wales: [-3.1791, 51.4816],
    'northern-ireland': [-5.9301, 54.5973]
  };
  Object.entries(capitals).forEach(([key, point]) => {
    const matches = nations.features.filter(feature => feature.polygons.some(ring => contains(point, ring)));
    assert.deepEqual(matches.map(feature => feature.key), [key]);
  });
  assert.ok(!nations.features.some(feature => feature.polygons.some(ring => contains([-6.2603, 53.3498], ring))), 'Dublin must remain outside UK nation overlays');
});
