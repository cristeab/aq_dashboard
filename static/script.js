// script.js

// Example data (replace with real sensor data from APIs or devices)
const dummyData = {
	aqi: "0",
	pm10: "0",
	pm25: "0",
	pm100: "0",
	pm03plus: "0",
	pm05plus: "0",
	pm10plus: "0",
	pm25plus: "0",
	pm50plus: "0",
	pm100plus: "0",
	temperature: "0",
	humidity: "0",
	pressure: "0",
	altitude: "0",
	tvoc: "0",
	noise: "0"
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

function drawTickMark(aqi) {
    const angle = Math.PI * (0.75 + (1.5 * aqi) / 500);
    const innerTickX = centerX + (radius - 10) * Math.cos(angle);
    const innerTickY = centerY + (radius - 10) * Math.sin(angle);
    const outerTickX = centerX + (radius + 10) * Math.cos(angle);
    const outerTickY = centerY + (radius + 10) * Math.sin(angle);

    // Get the tick mark color from CSS variables
    const tickMarkColor = getComputedStyle(document.documentElement).getPropertyValue('--tick-mark-color');

    // Draw tick mark
    ctx.beginPath();
    ctx.moveTo(innerTickX, innerTickY);
    ctx.lineTo(outerTickX, outerTickY);
    ctx.lineWidth = 2;
    ctx.strokeStyle = tickMarkColor;
    ctx.stroke();
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
	drawArc(); // Redraw the arc to clear the previous tick mark
	if (aqi !== undefined) {
		drawTickMark(aqi);
		document.getElementById('aqi-value').textContent = aqi;
		document.getElementById('aqi-label').textContent = getLabelForAQI(aqi);
	}
}

function updateElementVisibility(elementId, value, unit = "") {
	const element = document.getElementById(elementId);
	if (value !== undefined) {
		element.textContent = value + (unit ? ` ${unit}` : "");
		element.parentElement.style.display = ""; // Ensure it's visible
	} else {
		element.parentElement.style.display = "none"; // Hide the parent container
	}
}

function updateElementPrecisionVisibility(elementId, value, unit = "", precision = 1) {
	const element = document.getElementById(elementId);
	if (value !== undefined) {
		element.textContent = parseFloat(value).toFixed(precision) + (unit ? ` ${unit}` : "");
		element.parentElement.style.display = ""; // Ensure it's visible
	} else {
		element.parentElement.style.display = "none"; // Hide the parent container
	}
}

// Function to update the UI with sensor data
function updateDashboard(data)
{
	// Update date-time
	updateElementVisibility("date-time", data.timestamp);

	// Draw AQI Arc
	updateAQI(data.aqi);

	updateElementVisibility("pm1.0_0", data.pm10_0, "µg/m³");
	updateElementVisibility("pm1.0_1", data.pm10_1, "µg/m³");

	updateElementVisibility("pm2.5_0", data.pm25_0, "µg/m³");
	updateElementVisibility("pm2.5_1", data.pm25_1, "µg/m³");

	updateElementVisibility("pm10_0", data.pm100_0, "µg/m³");
	updateElementVisibility("pm10_1", data.pm100_1, "µg/m³");

	updateElementVisibility("pm0.3plus_0", data.pm03plus_0);
	updateElementVisibility("pm0.3plus_1", data.pm03plus_1);

	updateElementVisibility("pm0.5plus_0", data.pm05plus_0);
	updateElementVisibility("pm0.5plus_1", data.pm05plus_1);

	updateElementVisibility("pm1.0plus_0", data.pm10plus_0);
	updateElementVisibility("pm1.0plus_1", data.pm10plus_1);

	updateElementVisibility("pm2.5plus_0", data.pm25plus_0);
	updateElementVisibility("pm2.5plus_1", data.pm25plus_1);

	updateElementVisibility("pm5.0plus_0", data.pm50plus_0);
	updateElementVisibility("pm5.0plus_1", data.pm50plus_1);

	updateElementVisibility("pm10plus_0", data.pm100plus_0);
	updateElementVisibility("pm10plus_1", data.pm100plus_1);

	updateElementPrecisionVisibility("noise-value", data.noise, "dB");

	updateElementPrecisionVisibility("temp-value", data.temperature, "°C");
	updateElementPrecisionVisibility("humidity-value", data.relative_humidity, "%");
	updateElementPrecisionVisibility("pressure-value", data.pressure, "hPa");
	updateElementPrecisionVisibility("altitude-value", data.altitude, "m");
	
	const tvocElement = document.getElementById("tvoc-value");
	if (data.gas !== undefined) {	
		if (1000 <= data.gas) {
			tvocElement.textContent = parseFloat(data.gas / 1000).toFixed(1) + " k\u03A9";
		} else {
			tvocElement.textContent = data.gas + " \u03A9";
		}
		tvocElement.parentElement.style.display = ""; // Ensure it's visible
	} else {
		tvocElement.parentElement.style.display = "none"; // Hide the parent container
	}
}

document.addEventListener("DOMContentLoaded", function() {
    // Hard-coded variable to set the theme
    const useDarkTheme = true; // Change this to false for light theme
    if (useDarkTheme) {
        document.body.classList.add('dark-theme');
    } else {
        document.body.classList.remove('dark-theme');
    }

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
