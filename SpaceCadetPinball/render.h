#pragma once
#include "gdrv.h"
#include "maths.h"
#include "zdrv.h"

enum class VisualTypes : char
{
	Background = 0,
	Sprite = 1,
	Ball = 2
};

struct render_sprite
{
	rectangle_type BmpRect{};
	gdrv_bitmap8* Bmp;
	zmap_header_type* ZMap;
	bool DeleteFlag;
	VisualTypes VisualType;
	uint16_t Depth;
	rectangle_type DirtyRectPrev{};
	int ZMapOffestY;
	int ZMapOffestX;
	rectangle_type DirtyRect{};
	std::vector<render_sprite*>* OccludedSprites;
	rectangle_type BoundingRect{};
	bool DirtyFlag{};

	// Set by a playfield layout to take a sprite off the table without
	// destroying it. The sprite keeps its slot in the render list, so the
	// draw order of everything else is untouched and showing it again is a
	// single assignment.
	bool Hidden{};

	// Ball motion trail: recently occupied top-left positions, oldest first.
	// Only meaningful for VisualTypes::Ball sprites.
	enum { TrailCapacity = 24 };
	int TrailX[TrailCapacity]{};
	int TrailY[TrailCapacity]{};
	int TrailCount = 0;

	render_sprite(VisualTypes visualType, gdrv_bitmap8* bmp, zmap_header_type* zMap,
	              int xPosition, int yPosition, rectangle_type* boundingRect);
	~render_sprite();
	void set(gdrv_bitmap8* bmp, zmap_header_type* zMap, int xPos, int yPos);
	void ball_set(gdrv_bitmap8* bmp, float depth, int xPos, int yPos);
};


class render
{
public:
	static gdrv_bitmap8 *vscreen, *background_bitmap;
	static zmap_header_type* background_zmap;
	static int zmap_offsetX, zmap_offsetY;
	static SDL_Rect DestinationRect;

	static void init(gdrv_bitmap8* bmp, int width, int height);
	static void uninit();
	static void recreate_screen_texture();
	static void update();
	static void AddSprite(render_sprite& sprite);
	static void RemoveSprite(render_sprite& sprite);
	static void set_background_zmap(zmap_header_type* zMap, int offsetX, int offsetY);
	static void shift(int offsetX, int offsetY);
	static void build_occlude_list();
	static void SpriteViewer(bool* show);
	static void PresentVScreen();

	// Forces a full repaint of the next frame. Needed when something changed the
	// pixels of a bitmap that is already on screen, e.g. swapping the playfield
	// skin, because the dirty rectangle system only tracks moved sprites.
	//
	// resetDepth also wipes the depth buffer and every saved ball rectangle. A
	// layout switch moves and removes sprites, so the old depth values would
	// mask the new arrangement and the saved rectangles would restore pixels
	// from a table that no longer exists.
	static void InvalidateAll(bool resetDepth = false);

	// Reads the rendered frame back from the GPU and writes it as a BMP. Used by
	// the -screenshot command line switch; unlike a screen grab it also works
	// while the desktop is locked.
	static bool SaveScreenshot(const char* path);
private:
	static std::vector<render_sprite*> sprite_list, ball_list;
	static int offset_x, offset_y;
	static rectangle_type vscreen_rect;
	static gdrv_bitmap8* ball_bitmap[20];
	static zmap_header_type* zscreen;

	static void repaint(const render_sprite& sprite);
	static void paint_balls();
	static void unpaint_balls();
};
