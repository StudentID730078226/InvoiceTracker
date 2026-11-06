(() => {
  const source = document.getElementById('spending-data');
  if (!source) return;
  const data = JSON.parse(source.textContent), host = document.getElementById('spending-chart');
  const group = document.getElementById('chart-group'), style = document.getElementById('chart-style');
  const detail = document.getElementById('chart-detail');
  const money = new Intl.NumberFormat(undefined, {style: 'currency', currency: data.currency});
  const ns = 'http://www.w3.org/2000/svg';
  function element(tag, attrs, text) {
    const node = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function draw() {
    host.replaceChildren(); detail.textContent = '';
    const rows = data[group.value], width = Math.max(740, host.clientWidth, rows.length * 26 + 120), height = 350;
    const left = 100, top = 25, bottom = 80, plot = height - top - bottom;
    const max = Math.max(...rows.map(r => Number(r.total)), 0) || 1;
    const step = (width - left - 25) / Math.max(rows.length, 1);
    const svg = element('svg', {viewBox: `0 0 ${width} ${height}`, width, height, role: 'group', 'aria-label': 'Invoice totals in ' + data.currency});
    for (let i = 0; i <= 4; i++) {
      const y = top + plot * i / 4;
      svg.append(element('line', {x1: left, x2: width - 20, y1: y, y2: y, stroke: '#d8e3e5'}));
      svg.append(element('text', {x: left - 8, y: y + 4, 'text-anchor': 'end'}, money.format(max * (1 - i / 4))));
    }
    const points = rows.map((row, i) => [left + step * (i + .5), top + plot * (1 - Number(row.total) / max)]);
    if (style.value === 'line') svg.append(element('polyline', {points: points.map(p => p.join(',')).join(' '), fill: 'none', stroke: '#006c67', 'stroke-width': 3}));
    rows.forEach((row, i) => {
      const [x, y] = points[i], description = `${row.label}: ${money.format(Number(row.total))} · ${row.count} invoice(s)`;
      const mark = style.value === 'line' ? element('circle', {cx: x, cy: y, r: 5}) :
        element('rect', {x: x - step * .34, y, width: step * .68, height: Math.max(2, top + plot - y)});
      mark.setAttribute('fill', '#006c67'); mark.setAttribute('tabindex', '0');
      mark.setAttribute('aria-label', description); mark.append(element('title', {}, description));
      for (const event of ['mouseenter', 'focus', 'click']) mark.addEventListener(event, () => {detail.textContent = description;});
      svg.append(mark);
      if (i % Math.max(1, Math.ceil(rows.length / 12)) === 0 || i === rows.length - 1) {
        const label = row.label.length > 24 ? row.label.slice(0, 22) + '…' : row.label;
        svg.append(element('text', {x, y: top + plot + 18, transform: `rotate(-25 ${x} ${top + plot + 18})`, 'text-anchor': 'end'}, label));
      }
    });
    host.append(svg);
  }
  group.addEventListener('change', () => {style.value = 'bar'; draw();});
  style.addEventListener('change', draw);
  window.addEventListener('resize', draw);
  draw();
})();
