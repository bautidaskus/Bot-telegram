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

const checkinNode = document.querySelector("#checkin-data");

if (checkinNode && window.Chart) {
  const history = JSON.parse(checkinNode.textContent).history;
  const canvas = document.querySelector("#checkin-chart");
  if (canvas) {
    new Chart(canvas, {
      type: "line",
      data: {
        labels: history.map((point) => point.fecha),
        datasets: [
          { label: "Día", data: history.map((point) => point.puntaje), borderColor: "#145c44", backgroundColor: "#145c44" },
          { label: "Ánimo", data: history.map((point) => point.animo), borderColor: "#d6794a", backgroundColor: "#d6794a" },
          { label: "Energía", data: history.map((point) => point.energia), borderColor: "#d7b95c", backgroundColor: "#d7b95c" },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false, spanGaps: true },
    });
  }
}
