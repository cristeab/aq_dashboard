// script.js

// Example data (replace with real sensor data from APIs or devices)
const dummyData = {
	aqi: "105",
	temperature: "17°C",
	humidity: "25%",
	pm10: "479 µg/m³",
	pm25: "45 µg/m³",
	pm100: "28 µg/m³",
	pm03plus: "10",
	pm05plus: "3",
	pm10plus: "2",
	pm25plus: "3",
	pm50plus: "0",
	pm100plus: "0"
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
	// Draw AQI Arc
	updateAQI(data.aqi);
	document.getElementById("temp-value").textContent = data.temperature;
	document.getElementById("humidity-value").textContent = data.humidity;

	document.getElementById("pm1.0").textContent = data.pm10;
	document.getElementById("pm2.5").textContent = data.pm25;
	document.getElementById("pm10").textContent = data.pm100;

	document.getElementById("pm0.3plus").textContent = data.pm03plus;
	document.getElementById("pm0.5plus").textContent = data.pm05plus;
	document.getElementById("pm1.0plus").textContent = data.pm10plus;
	document.getElementById("pm2.5plus").textContent = data.pm25plus;
	document.getElementById("pm5.0plus").textContent = data.pm50plus;
	document.getElementById("pm10plus").textContent = data.pm100plus;

	// Update date-time
	const now = new Date();
	document.getElementById("date-time").textContent = now.toLocaleString();
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
		const data = JSON.parse(event.data);
		// Update your dashboard with the received data
		updateDashboard(data);
	};
});
