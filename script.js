// script.js

// Example data (replace with real sensor data from APIs or devices)
const airQualityData = {
	aqi: "105",
	temperature: "17°C",
	humidity: "25%",
	co2: "479 ppm",
	pm25: "45 µg/m³",
	pm10: "28 µg/m³",
	hcho: "0.040 mg/m³",
	tvoc: "0.75 mg/m³"
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

	ctx.beginPath();
	ctx.arc(dotX, dotY, 5, 0, Math.PI * 2);
	ctx.fillStyle = "#fff";
	ctx.fill();
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

	document.getElementById("co2").textContent = data.co2;
	document.getElementById("pm25").textContent = data.pm25;
	document.getElementById("pm10").textContent = data.pm10;
	document.getElementById("hcho").textContent = data.hcho;
	document.getElementById("tvoc").textContent = data.tvoc;

	// Update date-time
	const now = new Date();
	document.getElementById("date-time").textContent = now.toLocaleString();
}

document.addEventListener("DOMContentLoaded", function() {
	drawArc();
	addAQILabels();
	updateDashboard(airQualityData);
	// Simulate real-time updates (replace with actual API calls)
	setInterval(() => { updateDashboard(airQualityData); },
		    3000); // Update every 3 seconds
});
