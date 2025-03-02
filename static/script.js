// script.js

// Example data (replace with real sensor data from APIs or devices)
const dummyData = {
	aqi: "0",
	pm10: "0 µg/m³",
	pm25: "0 µg/m³",
	pm100: "0 µg/m³",
	pm03plus: "0",
	pm05plus: "0",
	pm10plus: "0",
	pm25plus: "0",
	pm50plus: "0",
	pm100plus: "0",
	temperature: "0°C",
	humidity: "0%"
};

// Get the canvas element
const canvas = document.getElementById("aqi-arc");
const ctx = canvas.getContext("2d");

// Arc properties
const centerX = canvas.width / 2;
const centerY = canvas.height / 2;
const radius = 80;

// Define colors & labels based on AQI ranges
const aqiRanges = [
	{ max: 50, color: '#00E400', label: 'Good' },
	{ max: 100, color: '#FFFF00', label: 'Moderate' },
	{ max: 150, color: '#FF7E00', label: 'Unhealthy for Sensitive Groups' },
	{ max: 200, color: '#FF0000', label: 'Unhealthy' },
	{ max: 300, color: '#8F3F97', label: 'Very Unhealthy' },
	{ max: 500, color: '#7E0023', label: 'Hazardous' }
];

// Draw the colored arc
function drawArc()
{
	ctx.clearRect(0, 0, canvas.width, canvas.height);

	// Draw the full arc with all intervals
	let startAngle = Math.PI * 0.75;
	aqiRanges.forEach((range, index) => {
		const endAngle = Math.PI * (0.75 + (1.5 * range.max) / 500);

		ctx.beginPath();
		ctx.arc(centerX, centerY, radius, startAngle, endAngle);
		ctx.lineWidth = 15;
		ctx.strokeStyle = range.color;
		ctx.stroke();

		startAngle = endAngle;
	});
}

function drawDot(aqi)
{
    const angle = Math.PI * (0.75 + (1.5 * aqi) / 500);
    const dotX = centerX + radius * Math.cos(angle);
    const dotY = centerY + radius * Math.sin(angle);
  
    // Add shadow
    ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
    ctx.shadowBlur = 4;
    ctx.shadowOffsetX = 2;
    ctx.shadowOffsetY = 2;
  
    // Draw larger white dot
    ctx.beginPath();
    ctx.arc(dotX, dotY, 8, 0, Math.PI * 2);
    ctx.fillStyle = "#fff";
    ctx.fill();
  
    // Add contrasting outline
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#000";
    ctx.stroke();
  
    // Reset shadow
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 0;
}

function addAQILabels()
{
	const labelsContainer = document.createElement('div');
	labelsContainer.className = 'aqi-labels';

	aqiRanges.forEach((range, index) => {
		const label = document.createElement('div');
		label.className = 'aqi-label';
		label.textContent = range.max;

		const angle = Math.PI * (0.75 + (1.5 * range.max) / 500);
		const labelX = centerX + (radius + 20) * Math.cos(angle);
		const labelY = centerY + (radius + 20) * Math.sin(angle);

		label.style.left = `${labelX}px`;
		label.style.top = `${labelY}px`;
		label.style.transform = `translate(-50%, -50%) rotate(${
			angle + Math.PI / 2}rad)`;

		labelsContainer.appendChild(label);
	});

	canvas.parentNode.appendChild(labelsContainer);
}

function getLabelForAQI(aqi)
{
	const range = aqiRanges.find(range => aqi <= range.max);
	return range ? range.label : 'N/A';
}

// Function to update AQI
function updateAQI(aqi)
{
	drawDot(aqi);
	document.getElementById('aqi-value').textContent = aqi;
	document.getElementById('aqi-label').textContent = getLabelForAQI(aqi);
}

// Function to update the UI with sensor data
function updateDashboard(data)
{
	// Update date-time
	document.getElementById("date-time").textContent = data.timestamp;

	// Draw AQI Arc
	updateAQI(data.aqi);

	document.getElementById("pm1.0_0").textContent = data.pm10_0 + " µg/m³";
	document.getElementById("pm1.0_1").textContent = data.pm10_1 + " µg/m³";
	document.getElementById("pm2.5_0").textContent = data.pm25_0 + " µg/m³";
	document.getElementById("pm2.5_1").textContent = data.pm25_1 + " µg/m³";
	document.getElementById("pm10_0").textContent = data.pm100_0 + " µg/m³";
	document.getElementById("pm10_1").textContent = data.pm100_1 + " µg/m³";

	document.getElementById("pm0.3plus_0").textContent = data.pm03plus_0;
	document.getElementById("pm0.3plus_1").textContent = data.pm03plus_1;
	document.getElementById("pm0.5plus_0").textContent = data.pm05plus_0;
	document.getElementById("pm0.5plus_1").textContent = data.pm05plus_1;
	document.getElementById("pm1.0plus_0").textContent = data.pm10plus_0;
	document.getElementById("pm1.0plus_1").textContent = data.pm10plus_1;
	document.getElementById("pm2.5plus_0").textContent = data.pm25plus_0;
	document.getElementById("pm2.5plus_1").textContent = data.pm25plus_1;
	document.getElementById("pm5.0plus_0").textContent = data.pm50plus_0;
	document.getElementById("pm5.0plus_1").textContent = data.pm50plus_1;
	document.getElementById("pm10plus_0").textContent = data.pm100plus_0;
	document.getElementById("pm10plus_1").textContent = data.pm100plus_1;

	document.getElementById("temp-value").textContent = data.temperature + "°C";
	document.getElementById("humidity-value").textContent = data.humidity + "%";
}

document.addEventListener("DOMContentLoaded", function() {
	drawArc();
	addAQILabels();
	updateDashboard(dummyData);

	// Extract the IP address from the current URL
	const ipAddress = window.location.hostname;
	const port = window.location.port;

	// Connect to the WebSocket server
	const wsUrl = `wss://${ipAddress}:${port}/ws`;
	const socket = new WebSocket(wsUrl);
	socket.onmessage = function(event) {
		console.log(event.data);
		const data = JSON.parse(event.data);
		// Update your dashboard with the received data
		updateDashboard(data);
	};
});
