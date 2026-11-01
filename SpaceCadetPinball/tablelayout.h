#pragma once

// Alternate playfield layouts.
//
// A theme only repaints the playfield bitmap. A layout goes further and
// rebuilds the table itself: the rails, the slingshots, the bumper cluster,
// the target banks and the rollovers are moved to new world coordinates, their
// collision edges are re-registered in the broad-phase grid and a fresh set of
// walls is installed. The rules, the lamps, the scoring and the flippers are
// untouched, so a layout really is a second table rather than a second skin.
//
// Layout 0 is the table exactly as the .DAT authored it. The first time a
// layout is applied every edge, sprite and bitmap position is snapshotted;
// going back to 0 restores that snapshot verbatim, which makes switching
// lossless and repeatable.
class tablelayout
{
public:
	// Alternate layouts, the stock table not included.
	static int Count();
	// Name of alternate layout index (1..Count()), or "" when out of range.
	static const char* Name(int index);
	// 0 when the name is unknown.
	static int IndexOf(const char* name);

	static int Current();
	static const char* CurrentName();

	// Returns false when the switch could not be performed (no table yet).
	static bool Set(int index);
	static bool SetByName(const char* name);
	static void Next();

	// Re-applies the layout recorded in the options. Called once the table has
	// been (re)built, right after the table skin.
	static void ApplySaved();
};
