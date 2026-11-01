#include "pch.h"
#include "tablelayout.h"

#include <algorithm>
#include <cstdlib>
#include <fstream>

#include "loader.h"
#include "options.h"
#include "pb.h"
#include "render.h"
#include "TBall.h"
#include "TCircle.h"
#include "TCollisionComponent.h"
#include "TDemo.h"
#include "TEdgeBox.h"
#include "TEdgeManager.h"
#include "TEdgeSegment.h"
#include "THole.h"
#include "TKickout.h"
#include "TLine.h"
#include "TPinballTable.h"
#include "TRamp.h"
#include "TTableLayer.h"
#include "TTextBox.h"

#include "tablelayout_nebula.inc"

namespace
{
	// Names of the alternate layouts. Index 0 is always the shipped table, so
	// alternate N maps to kAlternateNames[N - 1].
	const char* const kAlternateNames[] = {"Nebula"};
	constexpr int kAlternateCount = static_cast<int>(sizeof(kAlternateNames) / sizeof(kAlternateNames[0]));

	// Middle of the playfield in world coordinates. A wall polyline does not
	// record which side the ball runs on, so the offset that keeps the ball off
	// the artwork is derived from this point instead.
	constexpr float kPlayfieldCentreX = 0.0f;
	constexpr float kPlayfieldCentreY = 1.0f;

	int currentIndex = 0;
	bool haveSnapshot = false;

	// Temporary breadcrumbs while the layouts are being brought up.
	void trace(const char* what, const char* detail = "")
	{
		const char* path = getenv("SP_LAYOUT_TRACE");
		if (!path)
			return;
		if (FILE* file = fopen(path, "a"))
		{
			fprintf(file, "%s %s\n", what, detail);
			fclose(file);
		}
	}

	// An edge whose position and collision group a layout is allowed to change.
	struct EdgeState
	{
		TEdgeSegment* Edge;
		TLine* Line;
		TCircle* Circle;
		unsigned int Group;
		float X0, Y0, X1, Y1;
	};

	// A bitmap whose .DAT XPosition/YPosition a layout may shift. Component
	// sprites are re-based from these values on every animation frame
	// (TPinballComponent::SpriteSet), so this is the only place a move sticks.
	struct BitmapState
	{
		gdrv_bitmap8* Bmp;
		int X, Y;
	};

	struct SpriteState
	{
		render_sprite* Sprite;
		int Left, Top;
		int BoundLeft, BoundTop;
	};

	struct ActiveState
	{
		TPinballComponent* Comp;
		char Flag;
	};

	struct KickoutState
	{
		TKickout* Comp;
		vector2 Centre;
	};

	std::vector<EdgeState> edges;
	std::vector<BitmapState> bitmaps;
	std::vector<SpriteState> sprites;
	std::vector<ActiveState> activeFlags;
	std::vector<KickoutState> kickouts;

	// Owns the walls of the alternate layouts. Created on first use; its edges
	// are registered while an alternate layout is active and dropped again when
	// the stock table comes back.
	class TLayoutWalls : public TCollisionComponent
	{
	public:
		explicit TLayoutWalls(TPinballTable* table): TCollisionComponent(table, -1, false) {}
	};

	TLayoutWalls* walls = nullptr;

	const NebulaPartOffset* find_part(const char* name)
	{
		if (!name)
			return nullptr;
		for (int index = 0; index < kNebulaPartCount; ++index)
		{
			if (strcmp(kNebulaParts[index].Name, name) == 0)
				return &kNebulaParts[index];
		}
		return nullptr;
	}

	// Holes, scoops and ramps also act on the ball through a field effect that
	// lives in the broad-phase grid rather than in EdgeList. Zeroing ActiveFlag
	// takes both the edges and the field out of the game in one move, and it is
	// the one flag every one of them consults on its own.
	bool owns_field(TPinballComponent* comp)
	{
		return dynamic_cast<TKickout*>(comp) != nullptr
			|| dynamic_cast<THole*>(comp) != nullptr
			|| dynamic_cast<TRamp*>(comp) != nullptr;
	}

	void unregister_edge(TEdgeSegment* edge)
	{
		auto manager = TTableLayer::edge_manager;
		if (!manager)
			return;
		const int boxCount = manager->MaxBoxX * manager->MaxBoxY;
		for (int index = 0; index < boxCount; ++index)
		{
			auto& list = manager->BoxArray[index].EdgeList;
			list.erase(std::remove(list.begin(), list.end(), edge), list.end());
		}
	}

	void unregister_field(field_effect_type* field)
	{
		auto manager = TTableLayer::edge_manager;
		if (!manager)
			return;
		const int boxCount = manager->MaxBoxX * manager->MaxBoxY;
		for (int index = 0; index < boxCount; ++index)
		{
			auto& list = manager->BoxArray[index].FieldList;
			list.erase(std::remove(list.begin(), list.end(), field), list.end());
		}
	}

	void snapshot_edge(TEdgeSegment* edge)
	{
		EdgeState state = {};
		state.Edge = edge;
		state.Group = edge->CollisionGroup;
		if (auto line = dynamic_cast<TLine*>(edge))
		{
			state.Line = line;
			state.X0 = line->X0;
			state.Y0 = line->Y0;
			state.X1 = line->X1;
			state.Y1 = line->Y1;
		}
		else if (auto circle = dynamic_cast<TCircle*>(edge))
		{
			state.Circle = circle;
			state.X0 = circle->Circle.Center.X;
			state.Y0 = circle->Circle.Center.Y;
			state.X1 = circle->Circle.RadiusSq;
		}
		else
		{
			// Flipper edges build their own geometry from the parts they were
			// handed and never move, so there is nothing to record.
			return;
		}
		edges.push_back(state);
	}

	void take_snapshot()
	{
		edges.clear();
		bitmaps.clear();
		sprites.clear();
		activeFlags.clear();
		kickouts.clear();

		auto* mainTable = pb::MainTable;
		if (!mainTable)
			return;

		// Every bitmap pointer is recorded once: a group can be referenced from
		// more than one place and a doubled shift would tear it away from its
		// sprite rectangle.
		std::vector<gdrv_bitmap8*> seenBitmaps;

		for (auto comp : mainTable->ComponentList)
		{
			if (auto coll = dynamic_cast<TCollisionComponent*>(comp))
			{
				for (auto edge : coll->EdgeList)
					snapshot_edge(edge);
			}

			if (comp->ListBitmap)
			{
				for (auto& data : *comp->ListBitmap)
				{
					if (!data.Bmp)
						continue;
					if (std::find(seenBitmaps.begin(), seenBitmaps.end(), data.Bmp) != seenBitmaps.end())
						continue;
					seenBitmaps.push_back(data.Bmp);
					BitmapState state = {data.Bmp, data.Bmp->XPosition, data.Bmp->YPosition};
					bitmaps.push_back(state);
				}
			}

			if (comp->RenderSprite && comp->RenderSprite->VisualType == VisualTypes::Sprite)
			{
				auto sprite = comp->RenderSprite;
				SpriteState state = {
					sprite,
					sprite->BmpRect.XPosition, sprite->BmpRect.YPosition,
					sprite->BoundingRect.XPosition, sprite->BoundingRect.YPosition
				};
				sprites.push_back(state);
			}

			// Only the flag of a field owner is ever touched, so it is the only
			// one worth restoring: overwriting every component's flag would undo
			// whatever the rules had switched off in the middle of a game.
			if (owns_field(comp))
			{
				ActiveState state = {comp, comp->ActiveFlag};
				activeFlags.push_back(state);
			}

			if (auto kickout = dynamic_cast<TKickout*>(comp))
			{
				KickoutState state = {kickout, kickout->Circle.Center};
				kickouts.push_back(state);
			}
		}

		haveSnapshot = true;
	}

	bool insidePlayfield(float x, float y)
	{
		return x >= -8.0f && x <= 8.0f && y >= -14.0f && y <= 15.0f;
	}

	bool touches_playfield(TCollisionComponent* coll)
	{
		for (auto edge : coll->EdgeList)
		{
			if (auto line = dynamic_cast<TLine*>(edge))
			{
				if (insidePlayfield(line->X0, line->Y0) || insidePlayfield(line->X1, line->Y1))
					return true;
			}
			else if (auto circle = dynamic_cast<TCircle*>(edge))
			{
				if (insidePlayfield(circle->Circle.Center.X, circle->Circle.Center.Y))
					return true;
			}
			else
			{
				// Flipper edges are the one case with geometry this module can
				// not read. They never move, and their owners are recognised by
				// sprite position below, so assume they are on the table.
				return true;
			}
		}
		return false;
	}

	bool sprite_on_playfield(const render_sprite* sprite)
	{
		const auto* mainTable = pb::MainTable;
		if (!mainTable || !sprite || sprite->BmpRect.Width <= 0 || sprite->BmpRect.Height <= 0)
			return false;

		// Component sprites are positioned relative to the playfield bitmap
		// (TPinballComponent subtracts XOffset/YOffset), so the playfield is the
		// rectangle starting at the origin. Everything to its right is the score
		// panel, which a layout must leave alone.
		const int centreX = sprite->BmpRect.XPosition + sprite->BmpRect.Width / 2;
		const int centreY = sprite->BmpRect.YPosition + sprite->BmpRect.Height / 2;
		return centreX >= 0 && centreX < mainTable->Width
			&& centreY >= 0 && centreY < mainTable->Height;
	}

	// Signs the offset so the collision surface ends up on the far side of the
	// drawn wall, away from the middle of the table.
	float polyline_offset(const float* points, int count, float offset)
	{
		int inward = 0;
		for (int index = 0; index + 1 < count; ++index)
		{
			const float dx = points[2 * (index + 1)] - points[2 * index];
			const float dy = points[2 * (index + 1) + 1] - points[2 * index + 1];
			const float length = sqrtf(dx * dx + dy * dy);
			if (length < 0.0001f)
				continue;

			// Clockwise perpendicular, matching maths::line_init.
			const float perpendicularX = dy / length;
			const float perpendicularY = -dx / length;
			const float midX = (points[2 * index] + points[2 * (index + 1)]) * 0.5f;
			const float midY = (points[2 * index + 1] + points[2 * (index + 1) + 1]) * 0.5f;
			const auto towardsCentre = perpendicularX * (kPlayfieldCentreX - midX)
				+ perpendicularY * (kPlayfieldCentreY - midY);
			inward += towardsCentre > 0.0f ? 1 : -1;
		}
		return inward > 0 ? -offset : offset;
	}

	// Nudges a coordinate back inside the broad-phase grid. The outer rails run
	// along the very edge of the playfield, so a wall pushed outwards by the
	// ball radius easily ends up a fraction past the boundary, where box
	// coordinates clamp and the segment can no longer be walked.
	float clamp_to_grid(float value, float min, float max)
	{
		constexpr float margin = 0.02f;
		if (value < min + margin)
			return min + margin;
		if (value > max - margin)
			return max - margin;
		return value;
	}

	// Installs one polyline as a chain of lines plus rounded corners, mirroring
	// what TEdgeSegment::install_wall does with the .DAT wall format.
	void install_polyline(TLayoutWalls* owner, unsigned int group, const float* points, int count, float offset)
	{
		if (count < 2)
			return;

		auto manager = TTableLayer::edge_manager;
		if (!manager)
			return;

		const float signedOffset = polyline_offset(points, count, offset);

		for (int index = 0; index + 1 < count; ++index)
		{
			auto* line = new TLine(owner, &owner->ActiveFlag, group,
			                       points[2 * index], points[2 * index + 1],
			                       points[2 * (index + 1)], points[2 * (index + 1) + 1]);
			line->Offset(signedOffset);

			line->X0 = clamp_to_grid(line->X0, manager->MinX, manager->MaxX);
			line->X1 = clamp_to_grid(line->X1, manager->MinX, manager->MaxX);
			line->Y0 = clamp_to_grid(line->Y0, manager->MinY, manager->MaxY);
			line->Y1 = clamp_to_grid(line->Y1, manager->MinY, manager->MaxY);
			maths::line_init(line->Line, line->X0, line->Y0, line->X1, line->Y1);

			owner->EdgeList.push_back(line);
		}

		if (signedOffset == 0.0f)
			return;

		for (int index = 1; index + 1 < count; ++index)
		{
			const float inX = points[2 * index] - points[2 * index - 2];
			const float inY = points[2 * index + 1] - points[2 * index - 1];
			const float outX = points[2 * index + 2] - points[2 * index];
			const float outY = points[2 * index + 3] - points[2 * index + 1];
			const float cross = inX * outY - inY * outX;
			if (cross == 0.0f)
				continue;
			if ((cross > 0.0f) != (signedOffset > 0.0f))
				continue;

			vector2 centre{
				clamp_to_grid(points[2 * index], manager->MinX, manager->MaxX),
				clamp_to_grid(points[2 * index + 1], manager->MinY, manager->MaxY)
			};
			auto* circle = new TCircle(owner, &owner->ActiveFlag, group, &centre, fabsf(signedOffset) * 1.001f);
			owner->EdgeList.push_back(circle);
		}
	}

	// Builds the wall set of the alternate layout once.
	TLayoutWalls* acquire_walls(TPinballTable* mainTable)
	{
		if (walls)
			return walls;

		walls = new TLayoutWalls(mainTable);

		const float offset = mainTable->CollisionCompOffset;
		constexpr unsigned int group = 1;

		for (int run = 0; run < kNebulaWallRuns; ++run)
		{
			const int first = kNebulaWallStart[run];
			const int last = kNebulaWallStart[run + 1];
			install_polyline(walls, group, &kNebulaWallPoints[first], (last - first) / 2, offset);
		}

		return walls;
	}

	// Registers or drops the wall set of the alternate layout. Callers lift the
	// edges out of the grid first, so this is safe to call on every switch
	// without tripping the duplicate-insert assertion in TEdgeManager.
	void register_walls(bool enabled)
	{
		if (!walls)
			return;
		for (auto edge : walls->EdgeList)
		{
			if (enabled)
				edge->place_in_grid(&walls->AABB);
			else
				unregister_edge(edge);
		}
		walls->ActiveFlag = enabled ? 1 : 0;
	}

	void place_kickout_field(TKickout* kickout)
	{
		unregister_field(&kickout->Field);
		TTableLayer::edges_insert_circle(&kickout->Circle, nullptr, &kickout->Field);
	}

	void dump(const char* path, int layout)
	{
		std::ofstream out(path);
		if (!out)
			return;

		auto* mainTable = pb::MainTable;
		out << "layout " << layout << " table " << mainTable->Width << "x" << mainTable->Height
			<< " at " << mainTable->XOffset << "," << mainTable->YOffset << "\n";

		for (auto comp : mainTable->ComponentList)
		{
			if (!comp->GroupName || !*comp->GroupName)
				continue;
			const auto* sprite = comp->RenderSprite;
			out << comp->GroupName;
			if (sprite)
			{
				out << " rect " << sprite->BmpRect.XPosition << "," << sprite->BmpRect.YPosition
					<< " " << sprite->BmpRect.Width << "x" << sprite->BmpRect.Height
					<< (sprite->Hidden ? " hidden" : "");
			}
			const auto* part = find_part(comp->GroupName);
			if (part)
				out << " part " << part->WorldX << "," << part->WorldY;
			out << "\n";
		}

		out << "walls edges " << (walls ? walls->EdgeList.size() : 0) << "\n";

		for (auto ball : mainTable->BallList)
		{
			out << "ball active " << static_cast<int>(ball->ActiveFlag)
				<< " pos " << ball->Position.X << "," << ball->Position.Y << "," << ball->Position.Z;
			if (ball->RenderSprite)
				out << " rect " << ball->RenderSprite->BmpRect.XPosition << "," << ball->RenderSprite->BmpRect.YPosition
					<< " " << ball->RenderSprite->BmpRect.Width << "x" << ball->RenderSprite->BmpRect.Height
					<< (ball->RenderSprite->Hidden ? " hidden" : "");
			out << "\n";
		}
	}
}

int tablelayout::Count()
{
	return kAlternateCount;
}

const char* tablelayout::Name(int index)
{
	if (index < 1 || index > kAlternateCount)
		return "";
	return kAlternateNames[index - 1];
}

int tablelayout::IndexOf(const char* name)
{
	if (!name || !*name)
		return 0;
	for (int index = 1; index <= kAlternateCount; ++index)
	{
		if (_stricmp(kAlternateNames[index - 1], name) == 0)
			return index;
	}
	return 0;
}

int tablelayout::Current()
{
	return currentIndex;
}

const char* tablelayout::CurrentName()
{
	return Name(currentIndex);
}

bool tablelayout::Set(int index)
{
	auto* mainTable = pb::MainTable;
	if (!mainTable || !TTableLayer::edge_manager)
		return false;

	if (index < 0 || index > kAlternateCount)
		index = 0;

	trace("begin");
	if (!haveSnapshot)
		take_snapshot();
	trace("snapshot");

	const bool alternate = index > 0;

	if (alternate)
		acquire_walls(mainTable);
	trace("walls-built");

	// Everything this module may touch is lifted out of the broad-phase grid
	// first, so re-registering can never trip the duplicate-insert assertion.
	for (auto& state : edges)
		unregister_edge(state.Edge);
	if (walls)
	{
		for (auto edge : walls->EdgeList)
			unregister_edge(edge);
	}

	trace("unregistered");
	// Put the table back exactly the way the .DAT authored it.
	for (auto& state : edges)
	{
		state.Edge->CollisionGroup = state.Group;
		if (state.Line)
		{
			state.Line->X0 = state.X0;
			state.Line->Y0 = state.Y0;
			state.Line->X1 = state.X1;
			state.Line->Y1 = state.Y1;
			maths::line_init(state.Line->Line, state.X0, state.Y0, state.X1, state.Y1);
		}
		else if (state.Circle)
		{
			state.Circle->Circle.Center = {state.X0, state.Y0};
			state.Circle->Circle.RadiusSq = state.X1;
		}
	}

	for (auto& state : bitmaps)
	{
		state.Bmp->XPosition = state.X;
		state.Bmp->YPosition = state.Y;
	}

	for (auto& state : sprites)
	{
		state.Sprite->BmpRect.XPosition = state.Left;
		state.Sprite->BmpRect.YPosition = state.Top;
		state.Sprite->BoundingRect.XPosition = state.BoundLeft;
		state.Sprite->BoundingRect.YPosition = state.BoundTop;
		state.Sprite->Hidden = false;
	}

	for (auto& state : activeFlags)
		state.Comp->ActiveFlag = state.Flag;

	for (auto& state : kickouts)
		state.Comp->Circle.Center = state.Centre;
	trace("reset");

	// A component is either part of the new layout, permanently kept (the ball,
	// the attract demo, the message boxes) or cleared off the table.
	for (auto comp : mainTable->ComponentList)
	{
		if (comp == walls)
			continue;
		if (!comp->GroupName || !*comp->GroupName)
			continue;
		if (dynamic_cast<TBall*>(comp) || dynamic_cast<TDemo*>(comp) || dynamic_cast<TTextBox*>(comp))
			continue;

		const auto* part = alternate ? find_part(comp->GroupName) : nullptr;
		if (part)
		{
			const float worldX = part->WorldX;
			const float worldY = part->WorldY;
			const int screenX = static_cast<int>(floorf(part->ScreenX + 0.5f));
			const int screenY = static_cast<int>(floorf(part->ScreenY + 0.5f));

			if (auto coll = dynamic_cast<TCollisionComponent*>(comp))
			{
				for (auto edge : coll->EdgeList)
				{
					if (auto line = dynamic_cast<TLine*>(edge))
					{
						line->X0 += worldX;
						line->Y0 += worldY;
						line->X1 += worldX;
						line->Y1 += worldY;
						maths::line_init(line->Line, line->X0, line->Y0, line->X1, line->Y1);
					}
					else if (auto circle = dynamic_cast<TCircle*>(edge))
					{
						circle->Circle.Center.X += worldX;
						circle->Circle.Center.Y += worldY;
					}
				}
			}

			if (comp->ListBitmap)
			{
				for (auto& data : *comp->ListBitmap)
				{
					if (!data.Bmp)
						continue;
					data.Bmp->XPosition += screenX;
					data.Bmp->YPosition += screenY;
				}
			}

			if (comp->RenderSprite)
			{
				comp->RenderSprite->BmpRect.XPosition += screenX;
				comp->RenderSprite->BmpRect.YPosition += screenY;
				comp->RenderSprite->BoundingRect.XPosition += screenX;
				comp->RenderSprite->BoundingRect.YPosition += screenY;
			}

			if (auto kickout = dynamic_cast<TKickout*>(comp))
				kickout->Circle.Center = {kickout->Circle.Center.X + worldX, kickout->Circle.Center.Y + worldY};
			continue;
		}

		if (!alternate)
			continue;

		// Not in the layout: take it off the table. Collision edges keep their
		// geometry but lose the ball's collision group, which makes them
		// invisible to every query while staying reusable for the stock table.
		auto* coll = dynamic_cast<TCollisionComponent*>(comp);
		const bool onTable = coll ? touches_playfield(coll) : sprite_on_playfield(comp->RenderSprite);
		if (!onTable)
			continue;

		if (coll)
		{
			for (auto edge : coll->EdgeList)
				edge->CollisionGroup = 0;

			// Holes, scoops and ramps also pull the ball through a field effect
			// that is registered in the grid, not in EdgeList.
			if (owns_field(comp))
				comp->ActiveFlag = 0;
		}

		if (comp->RenderSprite)
			comp->RenderSprite->Hidden = true;
	}

	trace("components");
	// Re-register whatever is still on the table.
	for (auto& state : edges)
	{
		if (state.Edge->CollisionGroup == 0)
			continue;
		state.Edge->place_in_grid(&state.Edge->CollisionComponent->AABB);
	}

	trace("edges-registered");
	register_walls(alternate);
	trace("walls-registered");

	// Scoop gravity fields follow their scoop.
	for (auto& state : kickouts)
	{
		if (state.Comp->ActiveFlag)
			place_kickout_field(state.Comp);
	}

	trace("fields");
	render::build_occlude_list();
	trace("occluders");
	// Sprites moved or disappeared, so the depth buffer and every saved ball
	// rectangle refer to a table that no longer exists.
	render::InvalidateAll(true);
	trace("invalidated");

	currentIndex = index;
	options::Options.TableLayout.V = CurrentName();

	if (const char* dumpPath = getenv("SP_LAYOUT_DUMP"))
		dump(dumpPath, currentIndex);

	return true;
}

bool tablelayout::SetByName(const char* name)
{
	return Set(IndexOf(name));
}

void tablelayout::Next()
{
	Set((currentIndex + 1) % (kAlternateCount + 1));
}

void tablelayout::ApplySaved()
{
	// A (re)built table invalidates every pointer and edge we cached.
	haveSnapshot = false;
	walls = nullptr;

	edges.clear();
	bitmaps.clear();
	sprites.clear();
	activeFlags.clear();
	kickouts.clear();

	currentIndex = 0;

	const auto wanted = options::Options.TableLayout.V;
	Set(IndexOf(wanted.c_str()));
}
