const test = require('node:test');
const assert = require('node:assert/strict');
const { markerRadius, overviewRadius, clusterSites, layoutSites, project, REFERENCE_MW, OVERVIEW_REFERENCE_MW } = require('../generation-map.js');

test('capacity scales circle area against the fixed MW domain', () => {
  assert.equal(REFERENCE_MW, 25000);
  assert.equal(markerRadius(6250, 1), 9);
  assert.equal(markerRadius(25000, 1), 18);
  assert.equal(markerRadius(25000, 1) ** 2 / markerRadius(6250, 1) ** 2, 4);
  assert.ok(markerRadius(9982.71)>markerRadius(5728.48));
});
test('zooming out shrinks bubbles; detail and unknown sizes remain bounded', () => {
  assert.ok(markerRadius(5000, .5) < markerRadius(5000, 1));
  assert.ok(markerRadius(1250, .5) < markerRadius(1250, 1));
  assert.ok(markerRadius(1250, 4) < markerRadius(1250, 8));
  assert.equal(markerRadius(1e9, 64), 22);
  assert.equal(markerRadius(null, 1), 2);
  assert.equal(markerRadius(-10, 1), 2);
});
test('nearby bins retain every member in a deterministic order', () => {
  const points = [{ id: 'a', x: 1, y: 2, capacityMW: 5000 }, { id: 'b', x: 12, y: 5, capacityMW: 5000 }, { id: 'c', x: 60, y: 2 }];
  const groups = clusterSites(points);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups.map(g => g.count), [2, 1]);
  assert.equal(groups.reduce((n, g) => n + g.count, 0), 3);
  assert.deepEqual(clusterSites([...points].reverse()).map(group=>group.key), groups.map(group=>group.key));
});
test('co-located assets stay one bounded cluster at every zoom scale', () => {
  const world = project(-1, 53);
  for (const scale of [1000, 10000, 100000]) {
    const groups = clusterSites(Array.from({ length: 1000 }, (_, id) => ({ id, x: world.x * scale, y: world.y * scale })));
    assert.equal(groups.length, 1);
    assert.equal(groups[0].count, 1000);
  }
});
test('groups conserve installed MW at weighted member positions without grid displacement', () => {
  const points = [
    { id: 'large', x: 10, y: 10, site: { capacityMW: 1000, type:'gas' } },
    { id: 'small-a', x: 17, y: 12, site: { capacityMW: 1, type:'solar' } },
    { id: 'small-b', x: 20, y: 14, site: { capacityMW: 2, type:'solar' } }
  ];
  const items = layoutSites(points);
  assert.equal(items.length,1);
  assert.equal(items[0].kind,'cluster');
  assert.equal(items[0].count,3);
  assert.equal(items[0].capacityMW,1003);
  assert.equal(items[0].type,'mixed');
  assert.equal(items[0].x,(1000*10+17+2*20)/1003);
  assert.equal(items[0].y,(1000*10+12+2*14)/1003);
  assert.equal(markerRadius(items[0].capacityMW),markerRadius(1003));
});

test('unknown member capacities stay unavailable and zero is preserved',()=>{
  const group=layoutSites([{id:'known',x:2,y:2,site:{capacityMW:15}},{id:'unknown',x:3,y:3,site:{capacityMW:null}}])[0];
  assert.equal(group.capacityMW,null);
  assert.equal(group.knownCapacityMW,15);
  assert.equal(group.count,2);
  assert.equal(layoutSites([{id:'zero',x:2,y:2,site:{capacityMW:0}}])[0].capacityMW,0);
});

test('regional bubbles use a fixed area domain and shrink on zoom out',()=>{
  assert.equal(OVERVIEW_REFERENCE_MW,25000);
  assert.equal(overviewRadius(25000),20);
  assert.equal(overviewRadius(6250),10);
  assert.equal(overviewRadius(25000)**2/overviewRadius(6250)**2,4);
  assert.ok(overviewRadius(6250,.5)<overviewRadius(6250));
  assert.equal(overviewRadius(null),2);
  assert.ok(overviewRadius(32)<overviewRadius(900));
  assert.equal(overviewRadius(1e9,64),24);
});
