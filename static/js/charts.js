/**
 * SolarGuard AI - Real-Time Analytics & Chart Visualizations
 * Built on Chart.js 4.x
 */

let soilingTrendChart = null;
let conditionDoughnutChart = null;

// Initialize Chart Defaults for Dark Navy Industrial Theme
function initChartDefaults() {
  if (typeof Chart === 'undefined') return;

  Chart.defaults.color = '#94a3b8';
  Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.07)';
  Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
}

/**
 * Initializes the Soiling Index Trend Line Chart
 */
function setupSoilingTrendChart(cleanThreshold = 22, heavyThreshold = 48) {
  const ctx = document.getElementById('soilingTrendCanvas');
  if (!ctx) return;

  if (soilingTrendChart) {
    soilingTrendChart.destroy();
  }

  // Create gradient fill
  const gradient = ctx.getContext('2d').createLinearGradient(0, 0, 0, 260);
  gradient.addColorStop(0, 'rgba(6, 214, 160, 0.4)');
  gradient.addColorStop(1, 'rgba(6, 214, 160, 0.0)');

  soilingTrendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Visual Soiling Index (%)',
          data: [],
          borderColor: '#06d6a0',
          backgroundColor: gradient,
          borderWidth: 2.5,
          pointRadius: 3,
          pointBackgroundColor: '#06d6a0',
          pointBorderColor: '#080d1a',
          pointHoverRadius: 6,
          fill: true,
          tension: 0.35
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          backgroundColor: '#141f36',
          titleColor: '#fff',
          bodyColor: '#06d6a0',
          borderColor: '#2e4370',
          borderWidth: 1,
          padding: 10,
          callbacks: {
            label: function(context) {
              return `Soiling: ${context.parsed.y.toFixed(1)}%`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: {
            display: false
          },
          ticks: {
            maxTicksLimit: 8,
            font: {
              size: 11
            }
          }
        },
        y: {
          min: 0,
          max: 100,
          grid: {
            color: 'rgba(255, 255, 255, 0.05)'
          },
          ticks: {
            stepSize: 20,
            callback: function(value) {
              return value + '%';
            }
          }
        }
      }
    }
  });
}

/**
 * Initializes the Condition Distribution Doughnut Chart
 */
function setupConditionDoughnutChart() {
  const ctx = document.getElementById('conditionDoughnutCanvas');
  if (!ctx) return;

  if (conditionDoughnutChart) {
    conditionDoughnutChart.destroy();
  }

  conditionDoughnutChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Clean', 'Moderately Dusty', 'Heavily Dusty'],
      datasets: [
        {
          data: [1, 0, 0],
          backgroundColor: [
            '#10b981', // Clean Emerald
            '#f59e0b', // Moderate Amber
            '#ef4444'  // Heavy Dusty Crimson
          ],
          borderColor: '#141f36',
          borderWidth: 3,
          hoverOffset: 6
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '72%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            boxWidth: 12,
            padding: 14,
            font: {
              size: 11
            }
          }
        },
        tooltip: {
          backgroundColor: '#141f36',
          borderColor: '#2e4370',
          borderWidth: 1
        }
      }
    }
  });
}

/**
 * Updates charts with latest telemetry statistics from /api/detection/stats
 */
function updateChartsWithStats(stats) {
  if (!stats) return;

  // 1. Update Trend Chart
  if (soilingTrendChart && stats.recent_trend) {
    const labels = stats.recent_trend.map(item => {
      const d = new Date(item.timestamp);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    });
    const values = stats.recent_trend.map(item => item.soiling_index);

    soilingTrendChart.data.labels = labels;
    soilingTrendChart.data.datasets[0].data = values;
    soilingTrendChart.update('none');
  }

  // 2. Update Doughnut Chart
  if (conditionDoughnutChart) {
    const clean = stats.clean_count || 0;
    const moderate = stats.moderate_count || 0;
    const heavy = stats.heavy_count || 0;

    if (clean === 0 && moderate === 0 && heavy === 0) {
      conditionDoughnutChart.data.datasets[0].data = [1, 0, 0];
    } else {
      conditionDoughnutChart.data.datasets[0].data = [clean, moderate, heavy];
    }
    conditionDoughnutChart.update();
  }
}

// Auto init on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  initChartDefaults();
  setupSoilingTrendChart();
  setupConditionDoughnutChart();
});
