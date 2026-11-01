#pragma once
#include <cstdint>

// Effect ball system. Each ball kind gives the pinball a distinct elemental
// identity: a coloured motion trail, a glowing halo around the sphere, and a
// matching floating-score accent. Inspired by the pixelfx vocabulary
// (fire / ice / lightning / arcane / rainbow), but kept as plain palette
// colours so it slots into the existing 8-bit software renderer.
namespace balleffects
{
	enum class Kind : int
	{
		Normal = 0,
		Fire,
		Ice,
		Electric,
		Plasma,
		Rainbow,
		Ghost,
		Gold,
		Count
	};

	struct Style
	{
		const char* Name;
		uint8_t R, G, B;   // element colour used for the trail and halo
		float Glow;        // 0..1 strength of the halo drawn around the ball
		float Trail;       // 0..1 brightness multiplier for the trail
		bool Rainbow;      // cycle hue along the trail / over time
	};

	const Style& Get(Kind k);
	const char* Name(Kind k);
	inline int Count() { return static_cast<int>(Kind::Count); }

	// Hue-cycling colour for the Rainbow ball. t wraps over [0,1).
	void RainbowColor(float t, uint8_t& r, uint8_t& g, uint8_t& b);
}
