const dataNode = document.querySelector("#finance-data");

if (dataNode && window.Chart) {
  const data = JSON.parse(dataNode.textContent);
  const dailyCanvas = document.querySelector("#daily-chart");
  const categoryCanvas = document.querySelector("#category-chart");

  if (dailyCanvas) {
    new Chart(dailyCanvas, {
      type: "bar",
      data: {
        labels: data.daily.map((point) => point.date),
        datasets: [
          { label: "Ingresos", data: data.daily.map((point) => point.income), backgroundColor: "#145c44" },
          { label: "Gastos", data: data.daily.map((point) => point.expenses), backgroundColor: "#d6794a" },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false },
    });
  }

  if (categoryCanvas && data.categories.length) {
    new Chart(categoryCanvas, {
      type: "doughnut",
      data: {
        labels: data.categories.map((point) => point.category),
        datasets: [{ data: data.categories.map((point) => point.amount), backgroundColor: ["#145c44", "#d6794a", "#d7b95c", "#708f7f", "#9d6f5c"] }],
      },
      options: { responsive: true, maintainAspectRatio: false },
    });
  }
}

const gymNode = document.querySelector("#gym-data");

if (gymNode && window.Chart) {
  const progression = JSON.parse(gymNode.textContent).progression;
  const canvas = document.querySelector("#gym-chart");
  if (canvas) {
    new Chart(canvas, {
      type: "line",
      data: {
        labels: progression.map((point) => point.date),
        datasets: [
          { label: "Peso máximo", data: progression.map((point) => point.max_weight), borderColor: "#145c44", backgroundColor: "#145c44" },
          { label: "1RM estimado", data: progression.map((point) => point.estimated_1rm), borderColor: "#d6794a", backgroundColor: "#d6794a" },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false },
    });
  }
}

const healthNode = document.querySelector("#health-data");

if (healthNode && window.Chart) {
  const history = JSON.parse(healthNode.textContent).history;
  const labels = history.map((point) => point.date);
  const lineOptions = { responsive: true, maintainAspectRatio: false, spanGaps: true };

  const weightCanvas = document.querySelector("#weight-chart");
  if (weightCanvas) {
    new Chart(weightCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Peso", data: history.map((point) => point.weight), borderColor: "#145c44", backgroundColor: "#145c44" },
          { label: "Media 7 días", data: history.map((point) => point.weight_average_7d), borderColor: "#d6794a", backgroundColor: "#d6794a" },
        ],
      },
      options: lineOptions,
    });
  }

  const wellbeingCanvas = document.querySelector("#wellbeing-chart");
  if (wellbeingCanvas) {
    new Chart(wellbeingCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Sueño (h)", data: history.map((point) => point.sleep_hours), borderColor: "#145c44", backgroundColor: "#145c44" },
          { label: "Ánimo", data: history.map((point) => point.mood), borderColor: "#d6794a", backgroundColor: "#d6794a" },
          { label: "Energía", data: history.map((point) => point.energy), borderColor: "#d7b95c", backgroundColor: "#d7b95c" },
        ],
      },
      options: lineOptions,
    });
  }

  const waterCanvas = document.querySelector("#water-chart");
  if (waterCanvas) {
    new Chart(waterCanvas, {
      type: "bar",
      data: { labels, datasets: [{ label: "Agua (l)", data: history.map((point) => point.water_l), backgroundColor: "#708f7f" }] },
      options: lineOptions,
    });
  }
}
