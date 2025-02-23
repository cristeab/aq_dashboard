// script.js

// Example data (replace with real sensor data from APIs or devices)
const airQualityData = {
    aqi: "75",
    temperature: "17°C",
    humidity: "25%",
    co2: "479 ppm",
    pm25: "45 µg/m³",
    pm10: "28 µg/m³",
    hcho: "0.040 mg/m³",
    tvoc: "0.75 mg/m³"
};

// Function to update the UI with sensor data
function updateDashboard(data) {
    document.getElementById("aqi").textContent = data.aqi;
    document.getElementById("temperature").textContent = data.temperature;
    document.getElementById("humidity").textContent = data.humidity;

    document.getElementById("co2").textContent = data.co2;
    document.getElementById("pm25").textContent = data.pm25;
    document.getElementById("pm10").textContent = data.pm10;
    document.getElementById("hcho").textContent = data.hcho;
    document.getElementById("tvoc").textContent = data.tvoc;

    // Update date-time
    const now = new Date();
    document.getElementById("date-time").textContent = now.toLocaleString();
}

// Simulate real-time updates (replace with actual API calls)
setInterval(() => {
    updateDashboard(airQualityData);
}, 60000); // Update every minute

// Initial load
updateDashboard(airQualityData);
