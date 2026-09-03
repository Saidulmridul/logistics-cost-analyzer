document.addEventListener('DOMContentLoaded', function () {
  var dataEl = document.getElementById('chart-data');
  if (!dataEl) return;

  var charts;
  try {
    charts = JSON.parse(dataEl.textContent);
  } catch (e) {
    console.error('Could not parse chart data', e);
    return;
  }

  Object.keys(charts).forEach(function (key) {
    var el = document.getElementById(key);
    if (!el) return;
    var spec = charts[key];
    Plotly.newPlot(el, spec.data, spec.layout, { responsive: true, displaylogo: false });
  });

  window.addEventListener('resize', function () {
    Object.keys(charts).forEach(function (key) {
      var el = document.getElementById(key);
      if (el) Plotly.Plots.resize(el);
    });
  });
});

// Auto-open a details filter group if it already has selections, so the
// user can see what's active without an extra click.
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.filter-group .filter-count').forEach(function (badge) {
    var details = badge.closest('details');
    if (details) details.open = true;
  });
});
