#pragma once

#include <string>
#include <vector>

#include "gdrv.h"

struct gdrv_bitmap8;

// Runtime playfield skins.
//
// The shipped table artwork is baked into the .DAT and is also the reference
// the collision geometry was authored against, so it can never be replaced on
// disk. Instead a skin only swaps the pixels of the loaded playfield bitmap:
// the depth map, the sprites and every collision edge stay exactly as they are.
// Selecting the stock table copies the original pixels back, which makes the
// switch lossless and repeatable.
class tabletheme
{
public:
	struct Entry
	{
		std::string Name;
		std::string Path;
		// Optional playfield layout this skin belongs to. A skin that only
		// recolours the stock table leaves it empty; "Nebula" carries its own
		// rails, slingshots and hardware placement.
		std::string Layout;
	};

	// Reads themes/themes.txt ("Display name|file.bmp|layout"). Falls back to
	// the skins that ship with the build when the manifest is missing.
	static void Scan();
	static const std::vector<Entry>& Entries() { return entries; }
	static int Count() { return static_cast<int>(entries.size()); }

	// 0 means the stock table, 1..Count() index into Entries().
	static int Current() { return current; }
	static std::string CurrentName();

	static void Set(int index);
	static void Next();

	// Re-applies the saved skin after the table has (re)loaded, e.g. on a
	// resolution change or a restart.
	static void ApplySaved();

private:
	static std::vector<Entry> entries;
	static int current;
	static gdrv_bitmap8* target;
	static std::vector<ColorRgba> original;

	static bool AcquireTarget();
	static bool ApplyFile(const std::string& path);
	static void Restore();
};
