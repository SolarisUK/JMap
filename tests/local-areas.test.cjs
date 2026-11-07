const test = require('node:test');
const assert = require('node:assert/strict');
const geometry = require('../UI/assets/local-areas.js');

function insideRing([x, y], ring) {
  let inside = false;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const [ax, ay] = ring[i];
    const [bx, by] = ring[i + 1];
    if ((ay > y) !== (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax) inside = !inside;
  }
  return inside;
}

function insideFeature(point, feature) {
  return feature.polygons.filter(ring => insideRing(point, ring)).length % 2 === 1;
}

test('official 2025 district geometry covers every UK nation with unique current ONS codes', () => {
  const features = geometry.features;
  assert.equal(geometry.year, 2025);
  assert.equal(features.length, 361);
  assert.equal(new Set(features.map(feature => feature.key)).size, 361);
  const counts = { E: 0, S: 0, W: 0, N: 0 };
  features.forEach(feature => {
    assert.match(feature.key, /^[ESWN]\d{8}$/);
    counts[feature.key[0]] += 1;
    assert.ok(feature.name.trim());
  });
  assert.deepEqual(counts, { E: 296, S: 32, W: 22, N: 11 });
  assert.equal(features.find(feature => feature.name === 'Barnsley').key, 'E08000038');
  assert.equal(features.find(feature => feature.name === 'Sheffield').key, 'E08000039');
  assert.ok(!features.some(feature => ['E08000016', 'E08000019'].includes(feature.key)));
});

test('district rings, bounds and label positions are finite WGS84 coordinates', () => {
  geometry.features.forEach(feature => {
    assert.ok(feature.polygons.length > 0);
    const [[west, south], [east, north]] = feature.bounds;
    assert.ok(west < east && south < north, `${feature.name} has ordered bounds`);
    assert.ok(west >= -9 && east <= 2 && south >= 49 && north <= 61);
    assert.equal(feature.labelPosition.length, 2);
    assert.ok(feature.labelPosition.every(Number.isFinite));
    feature.polygons.forEach(ring => {
      assert.ok(ring.length >= 4, `${feature.name} ring needs three vertices and closure`);
      assert.deepEqual(ring[0], ring.at(-1));
      assert.ok(new Set(ring.slice(0, -1).map(point => point.join(','))).size >= 3);
      ring.forEach(point => {
        assert.equal(point.length, 2);
        const [longitude, latitude] = point;
        assert.ok(Number.isFinite(longitude) && Number.isFinite(latitude));
        assert.ok(longitude >= west && longitude <= east);
        assert.ok(latitude >= south && latitude <= north);
      });
    });
  });
});

test('Cambridge remains an enclave excluded from South Cambridgeshire using even-odd rings', () => {
  assert.equal(geometry.fillRule, 'evenodd');
  const cambridge = geometry.features.find(feature => feature.key === 'E07000008');
  const surrounding = geometry.features.find(feature => feature.key === 'E07000012');
  const point = [0.1218, 52.2053];
  assert.equal(insideFeature(point, cambridge), true);
  assert.ok(surrounding.polygons.some(ring => insideRing(point, ring)), 'Surrounding exterior contains the enclave');
  assert.equal(insideFeature(point, surrounding), false, 'Interior hole must exclude Cambridge');
});

test('recognisable city centres join their correct reporting areas across all four nations', () => {
  const locations = [
    ['E09000001', [-0.092, 51.514]],
    ['S12000036', [-3.1883, 55.9533]],
    ['W06000015', [-3.1791, 51.4816]],
    ['N09000003', [-5.9301, 54.5973]]
  ];
  locations.forEach(([key, point]) => {
    const matches = geometry.features.filter(feature => insideFeature(point, feature));
    assert.deepEqual(matches.map(feature => feature.key), [key]);
  });
});

test('missing consumption coverage is explicit for Northern Ireland rather than fabricated zeros', () => {
  assert.deepEqual(geometry.unmatchedConsumptionCodes, []);
  assert.deepEqual(geometry.missingConsumptionCodes, geometry.features.filter(feature => feature.key.startsWith('N')).map(feature => feature.key));
  assert.match(geometry.license, /Open Government Licence/);
  assert.equal(geometry.attribution.length, 2);
});
