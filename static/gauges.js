// gauges.js - gauges drawn from the bands of an index profile

/**
 * Colored bands of a profile clipped to its display scale.
 * categories: [{id, color, to?}] ordered, the last one may be open ended.
 */
function profileBands(categories, min, max) {
	const bands = [];
	let from = -Infinity;
	categories.forEach(category => {
		const to = category.to === undefined ? Infinity : category.to;
		const start = Math.max(from, min);
		const end = Math.min(to, max);
		if (end > start) {
			bands.push({ id: category.id, color: category.color, from: start, to: end });
		}
		from = to;
	});
	return bands;
}

/** Category boundaries strictly inside the scale, used as tick labels. */
function innerBoundaries(bands) {
	return bands.slice(0, -1).map(band => band.to);
}

function formatTick(value) {
	const text = Number.isInteger(value) ? String(value) : value.toFixed(1);
	return text.replace('-', '−'); // typographic minus, like the displayed values
}

/** 270° arc gauge drawn on a canvas, with tick labels around it. */
class ArcGauge {
	constructor(container, options) {
		this.container = container;
		this.size = options.size;
		this.radius = options.radius;
		this.lineWidth = options.lineWidth;
		this.labelOffset = options.labelOffset;
		this.minLabelAngle = options.minLabelAngle || 0.2; // radians between two tick labels
		this.needleOverhang = options.needleOverhang ?? 4; // px beyond the band, must not reach the labels
		this.canvas = container.querySelector('canvas');
		this.labels = document.createElement('div');
		this.labels.className = 'gauge-labels';
		container.appendChild(this.labels);
	}

	angle(value) {
		const ratio = (Math.min(Math.max(value, this.min), this.max) - this.min) / (this.max - this.min);
		return Math.PI * (0.75 + 1.5 * ratio);
	}

	render({ bands, min, max, ticks, value }) {
		this.min = min;
		this.max = max;
		// crisp rendering on high density screens
		const ratio = window.devicePixelRatio || 1;
		if (this.canvas.width !== Math.round(this.size * ratio)) {
			this.canvas.width = Math.round(this.size * ratio);
			this.canvas.height = Math.round(this.size * ratio);
		}
		this.canvas.style.width = `${this.size}px`;
		this.canvas.style.height = `${this.size}px`;
		const ctx = this.canvas.getContext('2d');
		ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
		ctx.clearRect(0, 0, this.size, this.size);
		const center = this.size / 2;

		// straight (radial) ends of the bands: the context keeps its state between two renders,
		// so the line cap must be set explicitly (the needle is drawn with round caps)
		ctx.lineCap = 'butt';
		bands.forEach(band => {
			ctx.beginPath();
			ctx.arc(center, center, this.radius, this.angle(band.from), this.angle(band.to));
			ctx.lineWidth = this.lineWidth;
			ctx.strokeStyle = band.color;
			ctx.stroke();
		});
		// outline and separators: light colors (yellow) keep a 3:1 contrast with the background
		if (bands.length) {
			const style = getComputedStyle(document.body);
			ctx.strokeStyle = style.getPropertyValue('--gauge-outline') || 'rgba(0, 0, 0, 0.45)';
			ctx.lineWidth = 1;
			const first = this.angle(bands[0].from);
			const last = this.angle(bands[bands.length - 1].to);
			[this.radius - this.lineWidth / 2, this.radius + this.lineWidth / 2].forEach(r => {
				ctx.beginPath();
				ctx.arc(center, center, r, first, last);
				ctx.stroke();
			});
			[...bands.map(b => b.from), bands[bands.length - 1].to].forEach(value => {
				const angle = this.angle(value);
				const inner = this.radius - this.lineWidth / 2;
				const outer = this.radius + this.lineWidth / 2;
				ctx.beginPath();
				ctx.moveTo(center + inner * Math.cos(angle), center + inner * Math.sin(angle));
				ctx.lineTo(center + outer * Math.cos(angle), center + outer * Math.sin(angle));
				ctx.stroke();
			});
		}

		if (value !== undefined && value !== null && Number.isFinite(Number(value))) {
			const angle = this.angle(Number(value));
			const inner = this.radius - this.lineWidth / 2 - this.needleOverhang;
			const outer = this.radius + this.lineWidth / 2 + this.needleOverhang;
			ctx.save();
			ctx.beginPath();
			ctx.moveTo(center + inner * Math.cos(angle), center + inner * Math.sin(angle));
			ctx.lineTo(center + outer * Math.cos(angle), center + outer * Math.sin(angle));
			ctx.lineWidth = 3;
			ctx.lineCap = 'round';
			ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue('--tick-mark-color');
			ctx.stroke();
			ctx.restore();
		}

		this.labels.innerHTML = '';
		let previousAngle = -Infinity;
		ticks.forEach(tick => {
			// a tick is a value, or {value, label} (e.g. the level numbers of a banded index)
			const value = typeof tick === 'object' ? tick.value : tick;
			const angle = this.angle(value);
			if (angle - previousAngle < this.minLabelAngle) {
				return; // would overlap the previous label
			}
			previousAngle = angle;
			const label = document.createElement('div');
			label.className = 'gauge-label';
			label.textContent = typeof tick === 'object' ? tick.label : formatTick(tick);
			const r = this.radius + this.labelOffset;
			label.style.left = `${center + r * Math.cos(angle)}px`;
			label.style.top = `${center + r * Math.sin(angle)}px`;
			label.style.transform = `translate(-50%, -50%) rotate(${angle + Math.PI / 2}rad)`;
			this.labels.appendChild(label);
		});
	}
}

/**
 * Scales the font of an overlay down (to at least minScale) until all its
 * text lies inside a circle, e.g. the inner edge of an arc gauge. The font
 * sizes inside the overlay must be expressed in em.
 */
function fitTextInCircle(overlay, canvas, radius, minScale = 0.6) {
	overlay.style.fontSize = '';
	const furthestCorner = () => {
		const c = canvas.getBoundingClientRect();
		const cx = c.left + c.width / 2;
		const cy = c.top + c.height / 2;
		let max = 0;
		overlay.querySelectorAll('*').forEach(el => {
			if (!el.firstChild || el.firstChild.nodeType !== Node.TEXT_NODE) {
				return;
			}
			const range = document.createRange();
			range.selectNodeContents(el);
			for (const r of range.getClientRects()) {
				for (const [x, y] of [[r.left, r.top], [r.right, r.top], [r.left, r.bottom], [r.right, r.bottom]]) {
					max = Math.max(max, Math.hypot(x - cx, y - cy));
				}
			}
		});
		return max;
	};
	for (let scale = 1; furthestCorner() > radius && scale > minScale;) {
		scale = Math.max(minScale, scale - 0.06);
		overlay.style.fontSize = `${Math.round(scale * 100)}%`;
	}
}

/** Horizontal segmented bar with a marker at the current value. */
class BarGauge {
	constructor(container) {
		this.container = container;
		container.innerHTML = `
			<div class="bar-track"><div class="bar-marker"></div></div>
			<div class="bar-ticks"></div>`;
		this.track = container.querySelector('.bar-track');
		this.marker = container.querySelector('.bar-marker');
		this.ticks = container.querySelector('.bar-ticks');
	}

	render({ bands, min, max, ticks, value }) {
		const position = v => (Math.min(Math.max(v, min), max) - min) / (max - min) * 100;
		this.track.querySelectorAll('.bar-segment').forEach(segment => segment.remove());
		bands.forEach(band => {
			const segment = document.createElement('div');
			segment.className = 'bar-segment';
			segment.style.left = `${position(band.from)}%`;
			segment.style.width = `${position(band.to) - position(band.from)}%`;
			segment.style.background = band.color;
			this.track.insertBefore(segment, this.marker);
		});

		const hasValue = value !== undefined && value !== null && Number.isFinite(Number(value));
		this.marker.style.display = hasValue ? '' : 'none';
		if (hasValue) {
			this.marker.style.left = `${position(Number(value))}%`;
		}

		this.ticks.innerHTML = '';
		const width = this.track.getBoundingClientRect().width || 240;
		let previous = -Infinity;
		ticks.forEach(tick => {
			// a tick is a value, or {value, label} (e.g. converted to °F, formatted for the language)
			const value = typeof tick === 'object' ? tick.value : tick;
			const x = position(value) / 100 * width;
			if (x - previous < 26) {
				return; // would overlap the previous label
			}
			previous = x;
			const label = document.createElement('span');
			label.className = 'bar-tick';
			label.textContent = typeof tick === 'object' ? tick.label : formatTick(tick);
			label.style.left = `${position(value)}%`;
			this.ticks.appendChild(label);
		});
	}
}
