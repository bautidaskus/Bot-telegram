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
