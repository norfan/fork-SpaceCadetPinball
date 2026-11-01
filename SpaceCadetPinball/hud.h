#pragma once

// Transparent score toolbar drawn across the top of the window.
//
// The stock table reserves a whole column on the right for the scoreboard,
// which leaves the playfield cramped. That column is now clipped away for
// every skin, so the score has to live somewhere: it floats over the top of
// the table instead, on a scrim that fades into the artwork.
class hud
{
public:
	// Loads the oversized font used for the score readout. Must run while the
	// ImGui font atlas is still open, i.e. before the first frame.
	static void InitFont();

	// Draws the toolbar. Call once per frame, after the menu bar has been
	// submitted so the toolbar can sit underneath it.
	static void Draw();

	// Drops the floating score numbers, e.g. when a new game starts.
	static void Reset();
};
