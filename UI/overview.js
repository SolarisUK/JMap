const period = document.querySelector('#period');
const todayActual = 'M0 190C45 190 55 205 95 195S155 160 190 165 235 114 280 116';
const yesterdayActual = 'M0 195C45 195 55 209 95 201S155 170 190 174 235 129 280 130 325 143 370 113 425 83 470 88 510 78 525 78 605 114 645 130 680 146 700 153';

period.addEventListener('change', () => {
  const today = period.value === 'today';
  const values = { demand: today ? '4,820' : '4,707', peak: today ? '5,140' : '4,990', reserve: today ? '14.2' : '15.1', 'demand-change': today ? '↗ 2.4%' : '↗ 1.8%', comparison: today ? 'vs. yesterday' : 'vs. previous day', 'peak-time': today ? '18:30' : '18:00', 'alert-count': today ? '03' : '02', attention: today ? '1 requires attention' : 'No action required', 'open-count': today ? '03 open' : '02 recorded', 'chart-note': today ? 'As of 10:42' : 'Full day / historical', 'alert-summary': today ? 'One item needs your attention.' : 'Historical alerts. No action required.' };
  Object.entries(values).forEach(([id, value]) => { document.getElementById(id).textContent = value; });
  document.querySelector('#section-alert-count').textContent = today ? '03' : '02';
  document.querySelector('.alert-list .alert').hidden = !today;
  document.querySelector('#actual-line').setAttribute('d', today ? todayActual : yesterdayActual);
  document.querySelector('#actual-point').setAttribute('cx', today ? '280' : '700');
  document.querySelector('#actual-point').setAttribute('cy', today ? '116' : '153');
  document.querySelector('#current-marker').style.display = today ? '' : 'none';
  document.querySelector('.chart').setAttribute('aria-label', today ? "Today's illustrative forecast peaks at 5,140 MW at 18:30. Actual demand is 4,820 MW at 10:42." : "Yesterday's illustrative actual demand peaked at 4,990 MW at 18:00, below the forecast of 5,140 MW. The complete day's actual demand is shown.");
});

document.querySelector('#view-assets').addEventListener('click', (event) => {
  const button = event.currentTarget;
  const expanded = button.getAttribute('aria-expanded') === 'true';
  button.setAttribute('aria-expanded', String(!expanded));
  document.querySelector('#extra-assets').hidden = expanded;
  button.firstChild.textContent = expanded ? 'View all assets ' : 'Show fewer assets ';
});

document.querySelector('#export-report').addEventListener('click', () => {
  const rows = [['JMap Grid Operations — Demo Report'], ['Period', period.options[period.selectedIndex].text], ['Region', 'North district'], [], ['Metric', 'Value', 'Unit'], ['Demand', document.querySelector('#demand').textContent.replaceAll(',', ''), 'MW'], ['Peak forecast', document.querySelector('#peak').textContent.replaceAll(',', ''), 'MW'], ['Reserve margin', document.querySelector('#reserve').textContent, '%'], ['Alerts', document.querySelector('#alert-count').textContent], [], ['Assets — current snapshot'], ['Asset', 'Type', 'Output / Load', 'Status', 'Outlook']];
  document.querySelectorAll('table tbody tr').forEach(row => rows.push([...row.cells].map((cell, index) => {
    const text = cell.textContent.replace(/[→↗]/g, '').trim();
    return index === 0 ? text.replace(/^[0-9]+\s*/, '') : text;
  })));
  const csv = rows.map(row => row.map(value => '"' + String(value).replaceAll('"', '""') + '"').join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `jmap-${period.value}-report.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  document.querySelector('#export-status').textContent = 'Report exported as CSV.';
});

const navLinks = [...document.querySelectorAll('.section-links a')];
const sections = navLinks.map(link => document.querySelector(link.getAttribute('href')));
function updateNavigation() {
  const requested = sections.find(section => '#' + section.id === window.location.hash);
  const requestedBounds = requested?.getBoundingClientRect();
  const requestedVisible = requestedBounds && requestedBounds.top < window.innerHeight && requestedBounds.bottom > 0;
  const passed = sections.filter(section => section.getBoundingClientRect().top <= 180);
  // Forecast and alerts share a row on desktop. Preserve DOM order on ties,
  // and honour the selected anchor when the viewport cannot scroll it to the top.
  const nearest = passed.reduce((best, section) => !best || section.getBoundingClientRect().top > best.getBoundingClientRect().top + 1 ? section : best, null);
  const current = requestedVisible ? requested : nearest || sections[0];
  navLinks.forEach(link => {
    const active = link.getAttribute('href') === '#' + current.id;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
}
window.addEventListener('scroll', updateNavigation, { passive: true });
window.addEventListener('hashchange', updateNavigation);
updateNavigation();

const dataDialog = document.querySelector('#overview-data-dialog');
document.querySelector('#about-data').addEventListener('click', () => dataDialog.showModal());
document.querySelector('#close-dialog').addEventListener('click', () => dataDialog.close());
document.querySelector('#dialog-done').addEventListener('click', () => dataDialog.close());
dataDialog.addEventListener('click', event => {
  if (event.target !== dataDialog) return;
  const bounds = dataDialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dataDialog.close();
});
