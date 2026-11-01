#include "pch.h"
#include "tabletheme.h"

#include <fstream>

#include "loader.h"
#include "options.h"
#include "pb.h"
#include "render.h"
#include "tablelayout.h"

std::vector<tabletheme::Entry> tabletheme::entries;
int tabletheme::current = 0;
gdrv_bitmap8* tabletheme::target = nullptr;
std::vector<ColorRgba> tabletheme::original;

namespace
{
	const char* const DefaultSkins[] = {"neon-grid", "blueprint", "amber-dusk"};

	std::string trim(std::string s)
	{
		while (!s.empty() && (s.back() == '\r' || s.back() == '\n' || s.back() == ' ' || s.back() == '\t'))
			s.pop_back();
		size_t start = 0;
		while (start < s.size() && (s[start] == ' ' || s[start] == '\t'))
			++start;
		return s.substr(start);
	}

	// Splits "a|b|c" into its trimmed fields.
	std::vector<std::string> split(const std::string& line, char separator)
	{
		std::vector<std::string> fields;
		size_t start = 0;
		while (true)
		{
			const auto end = line.find(separator, start);
			fields.push_back(trim(line.substr(start, end == std::string::npos ? std::string::npos : end - start)));
			if (end == std::string::npos)
				break;
			start = end + 1;
		}
		return fields;
	}
}

void tabletheme::Scan()
{
	entries.clear();

	std::ifstream manifest(pb::make_path_name("themes/themes.txt"));
	if (manifest)
	{
		std::string line;
		while (std::getline(manifest, line))
		{
			line = trim(line);
			if (line.empty() || line[0] == '#')
				continue;

			const auto fields = split(line, '|');
			Entry entry;
			entry.Name = fields[0];
			const auto file = fields.size() > 1 ? fields[1] : fields[0];
			entry.Path = pb::make_path_name("themes/" + file + (file.size() > 4
				&& _stricmp(file.c_str() + file.size() - 4, ".bmp") == 0 ? "" : ".bmp"));
			if (fields.size() > 2)
				entry.Layout = fields[2];
			entries.push_back(entry);
		}
	}

	// No manifest (or an empty one): offer the skins that ship with the build.
	if (entries.empty())
	{
		for (const auto name : DefaultSkins)
			entries.push_back({name, pb::make_path_name(std::string("themes/") + name + ".bmp")});
	}
}

std::string tabletheme::CurrentName()
{
	if (current <= 0 || current > static_cast<int>(entries.size()))
		return "";
	return entries[current - 1].Name;
}

bool tabletheme::AcquireTarget()
{
	if (target)
		return true;

	auto handle = loader::query_handle("table");
	if (handle < 0)
		return false;

	visualStruct visual{};
	if (loader::query_visual(handle, 0, &visual) != 0)
		return false;

	target = visual.Bitmap.Bmp;
	return target != nullptr;
}

bool tabletheme::ApplyFile(const std::string& path)
{
	if (!AcquireTarget())
		return false;

	auto* loaded = SDL_LoadBMP(path.c_str());
	if (!loaded)
	{
		pb::ShowMessageBox(SDL_MESSAGEBOX_WARNING, "Table theme", ("Could not load " + path).c_str());
		return false;
	}

	auto* surface = SDL_ConvertSurfaceFormat(loaded, SDL_PIXELFORMAT_ARGB8888, 0);
	SDL_FreeSurface(loaded);
	if (!surface)
		return false;

	if (original.empty())
		original.assign(target->BmpBufPtr1, target->BmpBufPtr1 + target->Stride * target->Height);

	if (SDL_MUSTLOCK(surface))
		SDL_LockSurface(surface);

	const auto* src = static_cast<const uint32_t*>(surface->pixels);
	const int srcPitch = surface->pitch / 4;
	const int srcW = surface->w, srcH = surface->h;
	const int dstW = target->Width, dstH = target->Height;

	for (int y = 0; y < dstH; ++y)
	{
		// Bilinear sample, only really used when the skin was authored for a
		// different table resolution.
		const float srcY = (y + 0.5f) * srcH / dstH - 0.5f;
		int y0 = static_cast<int>(floorf(srcY));
		float fy = srcY - y0;
		int y1 = y0 + 1;
		if (y0 < 0) { y0 = 0; fy = 0; }
		if (y1 >= srcH) y1 = srcH - 1;

		auto* row0 = src + y0 * srcPitch;
		auto* row1 = src + y1 * srcPitch;
		auto* dst = &target->BmpBufPtr1[y * target->Stride];

		for (int x = 0; x < dstW; ++x)
		{
			const float srcX = (x + 0.5f) * srcW / dstW - 0.5f;
			int x0 = static_cast<int>(floorf(srcX));
			float fx = srcX - x0;
			int x1 = x0 + 1;
			if (x0 < 0) { x0 = 0; fx = 0; }
			if (x1 >= srcW) x1 = srcW - 1;

			const uint32_t p00 = row0[x0], p10 = row0[x1], p01 = row1[x0], p11 = row1[x1];
			uint32_t out = 0xFF000000u;
			for (int shift = 0; shift < 24; shift += 8)
			{
				const float c = ((p00 >> shift) & 0xff) * (1 - fx) * (1 - fy)
					+ ((p10 >> shift) & 0xff) * fx * (1 - fy)
					+ ((p01 >> shift) & 0xff) * (1 - fx) * fy
					+ ((p11 >> shift) & 0xff) * fx * fy;
				out |= (static_cast<uint32_t>(c + 0.5f) & 0xff) << shift;
			}
			dst[x].Color = out;
		}
	}

	if (SDL_MUSTLOCK(surface))
		SDL_UnlockSurface(surface);
	SDL_FreeSurface(surface);

	// Sprite viewer previews, if the window was ever opened.
	target->CreateTexture(options::Options.LinearFiltering ? "linear" : "nearest",
	                      SDL_TEXTUREACCESS_STREAMING);
	target->BlitToTexture();
	return true;
}

void tabletheme::Restore()
{
	if (!target || original.empty())
		return;

	std::copy(original.begin(), original.end(), target->BmpBufPtr1);
	target->CreateTexture(options::Options.LinearFiltering ? "linear" : "nearest",
	                      SDL_TEXTUREACCESS_STREAMING);
	target->BlitToTexture();
}

void tabletheme::Set(int index)
{
	const auto count = static_cast<int>(entries.size());
	if (index < 0 || index > count)
		index = 0;

	current = index;

	auto applied = true;
	if (current == 0)
		Restore();
	else
		applied = ApplyFile(entries[current - 1].Path);

	if (!applied)
	{
		current = 0;
		Restore();
	}

	options::Options.TableTheme.V = CurrentName();

	// A skin may bring its own playfield: the geometry has to follow the art,
	// otherwise the ball would bounce off rails that are no longer drawn. When
	// the layout really changed it has already repainted the screen, depth
	// buffer included, so the cheaper invalidation is only needed otherwise.
	if (!tablelayout::SetByName(current == 0 ? "" : entries[current - 1].Layout.c_str()))
		render::InvalidateAll();
}

void tabletheme::Next()
{
	const auto count = static_cast<int>(entries.size());
	if (count == 0)
		return;
	Set((current + 1) % (count + 1));
}

void tabletheme::ApplySaved()
{
	// A (re)loaded table hands us a brand new bitmap, so any previously cached
	// pointers and pixel backups are stale.
	target = nullptr;
	original.clear();

	Scan();

	const auto wanted = options::Options.TableTheme.V;
	int index = 0;
	for (auto i = 0u; i < entries.size(); ++i)
	{
		if (entries[i].Name == wanted || entries[i].Path.find(wanted) != std::string::npos)
		{
			index = static_cast<int>(i) + 1;
			break;
		}
	}

	current = -1; // force Set() to actually do the work
	Set(index);
}
