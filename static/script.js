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
	noise: "0",
	temperature: "0",
	humidity: "0",
	pressure: "0",
	gas: "0",
	iaq: "0",
	co2: "0",
	voc: "0",
	nox: "0",
	co: "0"
};

let currentData = dummyData;
let currentNotifications = [];
const seenNotifications = new Set();

let translations = {};

async function initTranslations() {
    try {
        const response = await fetch('static/translations.json');
        translations = await response.json();
    } catch (error) {
        console.error('Failed to load translations:', error);
    }
}

let currentLanguage = localStorage.getItem('language') || 'en';

function t(key) {
    const lang = currentLanguage || 'en';
    return (translations[lang] && translations[lang][key]) || (translations['en'] && translations['en'][key]) || key;
}

// Get the canvas element
const canvas = document.getElementById("aqi-arc");
const ctx = canvas.getContext("2d");

// Arc properties
const centerX = canvas.width / 2;
const centerY = canvas.height / 2;
const radius = 80;

// Define colors & labels based on AQI ranges
const aqiRanges = [
	{ max: 50, color: '#00E400', labelKey: 'aqi_good' },
	{ max: 100, color: '#FFFF00', labelKey: 'aqi_moderate' },
	{ max: 150, color: '#FF7E00', labelKey: 'aqi_unhealthy_sensitive' },
	{ max: 200, color: '#FF0000', labelKey: 'aqi_unhealthy' },
	{ max: 300, color: '#8F3F97', labelKey: 'aqi_very_unhealthy' },
	{ max: 500, color: '#7E0023', labelKey: 'aqi_hazardous' }
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
    const tickMarkColor = getComputedStyle(document.body).getPropertyValue('--tick-mark-color');

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
	return range ? t(range.labelKey) : t('na');
}

// Function to update AQI
function updateAQI(aqi)
{
	drawArc(); // Redraw the arc to clear the previous tick mark
	if (aqi === undefined) {
		document.getElementById('aqi-value').textContent = "N/A";
		document.getElementById('aqi-label').textContent = "";
	} else {
		drawTickMark(aqi);
		document.getElementById('aqi-value').textContent = aqi;
		document.getElementById('aqi-label').textContent = getLabelForAQI(aqi);
	}
}

function updateElementVisibility(elementId, value, unit = "") {
	const element = document.getElementById(elementId);
	if (value === undefined) {
		element.parentElement.style.display = "none"; // Hide the parent container
	} else {
		element.textContent = value + (unit ? ` ${unit}` : "");
		element.parentElement.style.display = ""; // Ensure it's visible
	}
}

function updateElementPrecisionVisibility(elementId, value, unit = "", precision = 1) {
	const element = document.getElementById(elementId);
	if (value === undefined) {
		element.parentElement.style.display = "none"; // Hide the parent container
	} else {
		element.textContent = Number.parseFloat(value).toFixed(precision) + (unit ? ` ${unit}` : "");
		element.parentElement.style.display = ""; // Ensure it's visible
	}
}

// Function to update the UI with sensor data
function updateDashboard(data)
{
	currentData = data;
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

	updateElementPrecisionVisibility("temp-value", data.temperature, "°C");
	updateElementPrecisionVisibility("humidity-value", data.relative_humidity, "%");
	updateElementPrecisionVisibility("heat-index-value", data.thom_discomfort_index, "°C");
	updateElementPrecisionVisibility("pressure-value", data.pressure, "hPa");
	updateElementPrecisionVisibility("noise-value", data.noise, "dB");
	updateElementPrecisionVisibility("visible-light-lux-value", data.visible_light_lux, "lux");
	updateElementPrecisionVisibility("uv-index-value", data.uv_index, "", 2);
	
	updateElementPrecisionVisibility("no2-value", data.no2, "ppb");
	updateElementPrecisionVisibility("o3-value", data.o3, "ppb");
	updateElementVisibility("co-value", data.co, "ppm");
	updateElementVisibility("voc-value", data.voc);
	updateElementVisibility("nox-value", data.nox);
	updateElementVisibility("co2-value", data.co2, "ppm");

	updateElementVisibility("radon-value", data.radon_week_avg, "Bq/m³");
}

function updateNotifications(notifications) {
    const notificationsList = document.getElementById('notifications-list');
    if (!notificationsList) return;

    currentNotifications = notifications || [];

    // Clear previous notifications
    notificationsList.innerHTML = "";

    // If no notifications, show a placeholder
    if (currentNotifications.length === 0) {
        const emptyItem = document.createElement('div');
        emptyItem.className = 'notification-item';
        emptyItem.textContent = t('no_notifications');
        notificationsList.appendChild(emptyItem);

        // Hide the red dot
        const dot = document.getElementById('notification-dot');
        if (dot) {
            dot.classList.add('hidden');
        }
        return;
    }

    // Add each notification
    currentNotifications.forEach(n => {
        const item = document.createElement('div');
        item.className = 'notification-item';

        // Localize parameter
        let localizedParam = t(`param_${n.parameter}`);
        if (localizedParam === `param_${n.parameter}`) {
            localizedParam = n.parameter.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        }

        // Localize message
        let localizedMsg = n.message;
        if (n.type === 'missing_data') {
            localizedMsg = t('notification_missing_data')
                .replace('{parameter}', localizedParam);
        } else if (n.type === 'data_alert') {
            const intervalKey = `interval_${n.interval_name}`;
            let localizedInterval = t(intervalKey);
            if (localizedInterval === intervalKey) {
                localizedInterval = n.interval_name;
            }

            const descKey = `desc_${n.parameter}_${n.interval_name}`;
            let localizedDesc = t(descKey);
            if (localizedDesc === descKey) {
                if (n.parameter === 'radon_week_avg' || n.parameter === 'radon_year_avg') {
                    const fallbackDescKey = `desc_radon_1day_avg_${n.interval_name}`;
                    localizedDesc = t(fallbackDescKey);
                    if (localizedDesc === fallbackDescKey) {
                        localizedDesc = n.interval_description || "";
                    }
                } else {
                    localizedDesc = n.interval_description || "";
                }
            }

            localizedMsg = t('notification_data_alert')
                .replace('{value}', Number(n.value).toFixed(1))
                .replace('{unit}', n.unit || '')
                .replace('{interval_name}', localizedInterval)
                .replace('{interval_desc}', localizedDesc);
        }

        // Layout: timestamp (small, right), parameter (bold), message (normal)
        item.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: bold;">${localizedParam}</span>
                <span style="font-size: 0.85em; color: #bbb;">${n.timestamp}</span>
            </div>
            <div style="margin-top: 0.3em;">${localizedMsg}</div>
        `;
        notificationsList.appendChild(item);
    });

    // Show red dot if there are any unseen notifications
    const hasUnseen = currentNotifications.some(n => {
        const key = `${n.parameter}-${n.timestamp}-${n.message}`;
        return !seenNotifications.has(key);
    });

    const dot = document.getElementById('notification-dot');
    if (dot) {
        if (hasUnseen) {
            dot.classList.remove('hidden');
        } else {
            dot.classList.add('hidden');
        }
    }
}

document.addEventListener("DOMContentLoaded", async function() {
    // Fetch translations
    await initTranslations();

    // Theme handling logic
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    
    function getPreferredTheme() {
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme) {
            return savedTheme;
        }
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function setTheme(theme) {
        if (theme === 'dark') {
            document.body.classList.add('dark-theme');
        } else {
            document.body.classList.remove('dark-theme');
        }
        localStorage.setItem('theme', theme);
        // Redraw AQI to update the tick mark color with the new theme colors
        if (currentData) {
            updateAQI(currentData.aqi);
        }
    }

    function updateLanguage(lang) {
        currentLanguage = lang;
        localStorage.setItem('language', lang);
        document.documentElement.lang = lang;

        // Update active class in dropdown options
        document.querySelectorAll('.language-option').forEach(btn => {
            if (btn.getAttribute('data-lang') === lang) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Update active code display on button
        const activeCodeEl = document.getElementById('language-active-code');
        if (activeCodeEl) {
            activeCodeEl.textContent = lang.toUpperCase();
        }

        // Translate elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            el.textContent = t(key);
        });

        // Translate title attribute of elements with data-i18n-title attribute
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            el.setAttribute('title', t(key));
        });

        // Explicitly update document title
        document.title = t('title');

        // Force update of AQI text and notifications with the new language text
        if (currentData) {
            updateAQI(currentData.aqi);
        }
        updateNotifications(currentNotifications);
    }

    // Initialize theme
    const initialTheme = getPreferredTheme();
    setTheme(initialTheme);

    // Initialize language
    updateLanguage(currentLanguage);

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', function() {
            const currentTheme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            setTheme(newTheme);
        });
    }

	drawArc();
	addAQILabels();
	updateDashboard(dummyData);

	// Connect to the WebSocket server with auto-reconnection
	function connectWebSocket() {
		const protocol = globalThis.location.protocol === 'https:' ? 'wss:' : 'ws:';
		const host = globalThis.location.host;
		let path = globalThis.location.pathname;
		if (!path.endsWith('/')) {
			path += '/';
		}
		const wsUrl = `${protocol}//${host}${path}ws`;
		const socket = new WebSocket(wsUrl);

		socket.onmessage = function(event) {
			const data = JSON.parse(event.data);
			if (data.type === "data") {
				updateDashboard(data.payload);
			} else if (data.type === "notification") {
				updateNotifications(data.payload);
			}
		};

		socket.onclose = function() {
			console.warn("WebSocket disconnected. Reconnecting in 5 seconds...");
			setTimeout(connectWebSocket, 5000);
		};

		socket.onerror = function(err) {
			console.error("WebSocket encountered an error:", err);
			socket.close();
		};
	}

	connectWebSocket();

	// Notifications dropdown logic
    const notificationsBtn = document.getElementById('notifications-btn');
    const notificationsList = document.getElementById('notifications-list');
    const languageBtn = document.getElementById('language-btn');
    const languageDropdown = document.getElementById('language-dropdown');

    if (notificationsBtn && notificationsList) {
        notificationsBtn.addEventListener('click', function(e) {
            notificationsList.classList.toggle('hidden');
            
            // Close language dropdown if open
            if (languageDropdown) {
                languageDropdown.classList.add('hidden');
            }

            // Mark all current notifications as seen
            currentNotifications.forEach(n => {
                const key = `${n.parameter}-${n.timestamp}-${n.message}`;
                seenNotifications.add(key);
            });

            // Hide the red dot
            const dot = document.getElementById('notification-dot');
            if (dot) {
                dot.classList.add('hidden');
            }

            e.stopPropagation();
        });
        document.addEventListener('click', function(event) {
            if (!notificationsBtn.contains(event.target) && !notificationsList.contains(event.target)) {
                notificationsList.classList.add('hidden');
            }
        });
		updateNotifications([]); // Initialize with empty notifications
    }

    // Language selection dropdown logic
    if (languageBtn && languageDropdown) {
        languageBtn.addEventListener('click', function(e) {
            languageDropdown.classList.toggle('hidden');
            
            // Close notifications list if open
            if (notificationsList) {
                notificationsList.classList.add('hidden');
            }

            e.stopPropagation();
        });

        document.querySelectorAll('.language-option').forEach(option => {
            option.addEventListener('click', function(e) {
                const lang = this.getAttribute('data-lang');
                updateLanguage(lang);
                languageDropdown.classList.add('hidden');
                e.stopPropagation();
            });
        });

        document.addEventListener('click', function(event) {
            if (!languageBtn.contains(event.target) && !languageDropdown.contains(event.target)) {
                languageDropdown.classList.add('hidden');
            }
        });
    }
});
