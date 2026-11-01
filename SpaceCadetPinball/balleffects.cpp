#include "balleffects.h"
#include <cmath>

namespace balleffects
{
	static const Style Styles[] =
	{
		// Name        R    G    B    Glow  Trail Rainbow
		{"Classic",  200, 220, 240, 0.0f, 1.0f, false},  // Normal: plain ball, no colour
		{"Fire",     255, 120,  30, 0.85f, 1.0f, false},
		{"Ice",      130, 220, 255, 0.80f, 1.0f, false},
		{"Electric", 175, 130, 255, 0.85f, 1.0f, false},
		{"Plasma",   255,  90, 200, 0.85f, 1.0f, false},
		{"Rainbow",  255, 255, 255, 0.80f, 1.0f, true },
		{"Ghost",    205, 235, 255, 0.45f, 0.7f, false},
		{"Gold",     255, 210,  90, 0.80f, 1.0f, false},
	};

	static_assert(static_cast<int>(Kind::Count) == sizeof(Styles) / sizeof(Styles[0]),
	              "balleffects::Styles must cover every Kind");

	const Style& Get(Kind k)
	{
		auto i = static_cast<int>(k);
		if (i < 0 || i >= static_cast<int>(Kind::Count))
			i = 0;
		return Styles[i];
	}

	const char* Name(Kind k)
	{
		return Get(k).Name;
	}

	void RainbowColor(float t, uint8_t& r, uint8_t& g, uint8_t& b)
	{
		// Full-spectrum sweep through the six primaries, wrapped.
		t = t - std::floor(t);
		const float h = t * 6.0f;
		const int sector = static_cast<int>(h) % 6;
		const float f = h - sector;
		const uint8_t up = static_cast<uint8_t>(255 * f);
		const uint8_t dn = static_cast<uint8_t>(255 * (1.0f - f));
		switch (sector)
		{
		case 0: r = 255; g = up;  b = 0;   break;
		case 1: r = dn;  g = 255; b = 0;   break;
		case 2: r = 0;   g = 255; b = up;  break;
		case 3: r = 0;   g = dn;  b = 255; break;
		case 4: r = up;  g = 0;   b = 255; break;
		default:r = 255; g = 0;   b = dn;  break;
		}
	}
}
