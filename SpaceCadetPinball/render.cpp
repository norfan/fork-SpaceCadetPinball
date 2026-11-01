#include "pch.h"
#include "render.h"

#include <algorithm>
#include <cmath>

#include "balleffects.h"
#include "fullscrn.h"
#include "GroupData.h"
#include "options.h"
#include "pb.h"
#include "score.h"
#include "TPinballTable.h"
#include "winmain.h"
#include "DebugOverlay.h"
#include "proj.h"

namespace
{
	// Longest distance a ghost may trail behind the ball, in vScreen pixels.
	constexpr int TrailMaxDistance = 120;

	// Largest ball bitmap seen in any of the DAT files.
	constexpr int MaxBallBitmapSize = 64;

	// Extra halo radius budget reserved around the ball so an effect ball's
	// glow fits inside the saved region (and is therefore restored correctly
	// on the following frame) without enlarging the trail margin itself.
	constexpr int MaxGlowRadius = 64;

	// Backing store for the region a ball (plus its trail and its glow) covers
	// on vScreen. Sized so the widest possible trail plus the largest halo fit.
	constexpr int BallSaveBufferSize =
		MaxBallBitmapSize + 2 * (TrailMaxDistance + MaxGlowRadius);

	// Alpha of the newest ghost. Older ones fade linearly from here down to
	// nearly zero, so the tail dissolves into the table instead of ending in a
	// hard edge.
	constexpr unsigned TrailMaxAlpha = 150;

	// Distance in vScreen pixels between two consecutive ghosts, and the cap on
	// how many of them one frame may insert (protects against teleports).
	constexpr double TrailGhostSpacing = 5.0;
	constexpr int TrailMaxSteps = 8;

	// Alpha-blended counterpart of zdrv::paint_flat. paint_flat copies pixels
	// verbatim; trail ghosts need to fade out towards the tail, otherwise they
	// would look like a second solid ball. When `style` is non-null the ghost
	// is tinted towards the element colour (and, for a rainbow ball, towards a
	// hue that advances along the tail) so the streak reads as elemental.
	void paint_ghost(int width, int height, int dstX, int dstY, int srcX, int srcY,
	                 gdrv_bitmap8* dstBmp, zmap_header_type* zMap, int zX, int zY,
	                 gdrv_bitmap8* srcBmp, uint16_t depth, unsigned alpha,
	                 const balleffects::Style* style, float hueT)
	{
		auto dstPtr = &dstBmp->BmpBufPtr1[dstBmp->Stride * dstY + dstX];
		auto srcPtr = &srcBmp->BmpBufPtr1[srcBmp->Stride * srcY + srcX];
		auto zPtr = &zMap->ZPtr1[zMap->Stride * zY + zX];
		const auto invAlpha = 255u - alpha;

		uint8_t er = 200, eg = 220, eb = 240;  // element colour, used only when style != nullptr
		float mix = 0.0f;
		if (style)
		{
			if (style->Rainbow)
				balleffects::RainbowColor(hueT, er, eg, eb);
			else
			{
				er = style->R; eg = style->G; eb = style->B;
			}
			// Coloured balls tint strongly; the pale Ghost kind tints less.
			mix = style->Rainbow ? 0.8f : 0.7f * style->Trail;
		}

		for (int y = height; y > 0; --y)
		{
			for (int x = width; x > 0; --x)
			{
				if (srcPtr->Color && *zPtr > depth)
				{
					auto dst = *dstPtr;
					const auto src = *srcPtr;
					// Tint the ghost pixel towards the element colour first
					// (mix = 0 keeps the classic look), then alpha-blend onto the
					// destination. A plain blend, not an accumulation, so
					// overlapping ghosts stay as bright as the ball itself.
					const uint8_t gR = static_cast<uint8_t>(src.GetRed()   * (1.0f - mix) + er * mix);
					const uint8_t gG = static_cast<uint8_t>(src.GetGreen() * (1.0f - mix) + eg * mix);
					const uint8_t gB = static_cast<uint8_t>(src.GetBlue()  * (1.0f - mix) + eb * mix);
					dst.SetRed(static_cast<uint8_t>((gR * alpha + dst.GetRed() * invAlpha) / 255));
					dst.SetGreen(static_cast<uint8_t>((gG * alpha + dst.GetGreen() * invAlpha) / 255));
					dst.SetBlue(static_cast<uint8_t>((gB * alpha + dst.GetBlue() * invAlpha) / 255));
					dst.SetAlpha(0xff);
					*dstPtr = dst;
				}
				++srcPtr;
				++dstPtr;
				++zPtr;
			}

			srcPtr += srcBmp->Stride - width;
			dstPtr += dstBmp->Stride - width;
			zPtr += zMap->Stride - width;
		}
	}

	// Solid ball painter. zdrv::paint_flat copies the sphere bitmap verbatim;
	// for an effect ball the sphere itself is tinted towards the element colour
	// so the ball and its trail read as one thing. The tint is a lerp towards
	// the element colour, which keeps the bitmap's own shading and highlight.
	void paint_ball(int width, int height, int dstX, int dstY, int srcX, int srcY,
	                gdrv_bitmap8* dstBmp, zmap_header_type* zMap, int zX, int zY,
	                gdrv_bitmap8* srcBmp, uint16_t depth,
	                const balleffects::Style* style, float hueT)
	{
		auto dstPtr = &dstBmp->BmpBufPtr1[dstBmp->Stride * dstY + dstX];
		auto srcPtr = &srcBmp->BmpBufPtr1[srcBmp->Stride * srcY + srcX];
		auto zPtr = &zMap->ZPtr1[zMap->Stride * zY + zX];

		uint8_t er = 200, eg = 220, eb = 240;
		float mix = 0.0f;
		if (style)
		{
			if (style->Rainbow)
				balleffects::RainbowColor(hueT, er, eg, eb);
			else
			{
				er = style->R; eg = style->G; eb = style->B;
			}
			mix = style->Rainbow ? 0.85f : 0.72f * style->Trail;
		}

		for (int y = height; y > 0; --y)
		{
			for (int x = width; x > 0; --x)
			{
				if (srcPtr->Color && *zPtr > depth)
				{
					const auto src = *srcPtr;
					// Lerp towards the element colour, then keep the source
					// luminance ratio so the sphere does not turn into a
					// flat coloured disc.
					const float lum = (src.GetRed() * 0.299f + src.GetGreen() * 0.587f + src.GetBlue() * 0.114f) / 255.0f;
					auto dst = *srcPtr;
					dst.SetRed(static_cast<uint8_t>(src.GetRed()   * (1.0f - mix) + er * mix * (0.35f + 0.65f * lum)));
					dst.SetGreen(static_cast<uint8_t>(src.GetGreen() * (1.0f - mix) + eg * mix * (0.35f + 0.65f * lum)));
					dst.SetBlue(static_cast<uint8_t>(src.GetBlue()  * (1.0f - mix) + eb * mix * (0.35f + 0.65f * lum)));
					dst.SetAlpha(0xff);
					*dstPtr = dst;
				}
				++srcPtr;
				++dstPtr;
				++zPtr;
			}

			srcPtr += srcBmp->Stride - width;
			dstPtr += dstBmp->Stride - width;
			zPtr += zMap->Stride - width;
		}
	}

	// Additive glow drawn around an effect ball. The profile is deliberately
	// two-zone: inside the ball's radius the element colour only tints the
	// sphere (so its own shading and highlight stay readable), and outside it
	// a halo peaks at the ball's edge and dies out at the outer radius. The
	// z-map is only read, never written, so anything drawn in front of the
	// ball occludes the glow for free. The caller must keep the affected
	// rectangle inside the saved dirty region.
	void paint_glow(int cx, int cy, int innerR, int outerR, uint8_t cr, uint8_t cg, uint8_t cb,
	                float strength, gdrv_bitmap8* dstBmp, zmap_header_type* zMap,
	                uint16_t depth, const rectangle_type& bounds)
	{
		if (outerR <= 0 || strength <= 0.0f)
			return;

		const int x0 = std::max(0, std::max(bounds.XPosition, cx - outerR));
		const int y0 = std::max(0, std::max(bounds.YPosition, cy - outerR));
		const int x1 = std::min(dstBmp->Width,  std::min(bounds.XPosition + bounds.Width,  cx + outerR + 1));
		const int y1 = std::min(dstBmp->Height, std::min(bounds.YPosition + bounds.Height, cy + outerR + 1));
		const float inner = static_cast<float>(std::max(1, innerR));
		const float outer = static_cast<float>(outerR);
		const float span = std::max(1.0f, outer - inner);

		for (int y = y0; y < y1; ++y)
		{
			auto* dstPtr = &dstBmp->BmpBufPtr1[dstBmp->Stride * y + x0];
			auto* zPtr   = &zMap->ZPtr1[zMap->Stride * y + x0];
			const int dy = y - cy;
			for (int x = x0; x < x1; ++x)
			{
				const int dx = x - cx;
				const float dist = std::sqrt(static_cast<float>(dx * dx + dy * dy));
				if (dist <= outer && *zPtr >= depth)
				{
					float intensity;
					if (dist <= inner)
					{
						// Core: a gentle tint that keeps the sphere readable.
						intensity = strength * 0.38f * (1.0f - 0.45f * (dist / inner));
					}
					else
					{
						// Halo: peaks at the ball's edge, fades to nothing.
						const float t = (dist - inner) / span;
						intensity = strength * (1.0f - t) * (1.0f - t);
					}
					auto dst = *dstPtr;
					dst.SetRed(static_cast<uint8_t>(std::min(255.f, dst.GetRed()   + cr * intensity)));
					dst.SetGreen(static_cast<uint8_t>(std::min(255.f, dst.GetGreen() + cg * intensity)));
					dst.SetBlue(static_cast<uint8_t>(std::min(255.f, dst.GetBlue()  + cb * intensity)));
					dst.SetAlpha(0xff);
					*dstPtr = dst;
				}
				++dstPtr;
				++zPtr;
			}
		}
	}

	// Animated phase driving the rainbow ball's hue cycle. Advanced once per
	// paint_balls call so the colour keeps shifting while the ball is in play.
	static float GlowPhase = 0.0f;
}

std::vector<render_sprite*> render::sprite_list, render::ball_list;
zmap_header_type* render::background_zmap;
int render::zmap_offsetX, render::zmap_offsetY, render::offset_x, render::offset_y;
rectangle_type render::vscreen_rect;
gdrv_bitmap8 *render::vscreen, *render::background_bitmap, *render::ball_bitmap[20];
zmap_header_type* render::zscreen;
SDL_Rect render::DestinationRect{};

render_sprite::render_sprite(VisualTypes visualType, gdrv_bitmap8* bmp, zmap_header_type* zMap,
	int xPosition, int yPosition, rectangle_type* boundingRect)
{
	Bmp = bmp;
	ZMap = zMap;
	VisualType = visualType;
	DeleteFlag = false;
	OccludedSprites = nullptr;
	DirtyRect = rectangle_type{};
	DirtyFlag = visualType != VisualTypes::Ball;
	ZMapOffestX = 0;
	ZMapOffestY = 0;
	Depth = 0xffFF;

	if (boundingRect)
	{
		BoundingRect = *boundingRect;
	}
	else
	{
		BoundingRect.Width = -1;
		BoundingRect.Height = -1;
		BoundingRect.XPosition = 0;
		BoundingRect.YPosition = 0;
	}

	BmpRect.XPosition = xPosition;
	BmpRect.YPosition = yPosition;
	if (bmp)
	{
		BmpRect.Width = bmp->Width;
		BmpRect.Height = bmp->Height;
	}
	else
	{
		BmpRect.Width = 0;
		BmpRect.Height = 0;
	}
	DirtyRectPrev = BmpRect;

	if (!ZMap && VisualType != VisualTypes::Ball)
	{
		assertm(false, "Background zMap should not be used");
		ZMap = render::background_zmap;
		ZMapOffestY = xPosition - render::zmap_offsetX;
		ZMapOffestX = yPosition - render::zmap_offsetY;
	}

	render::AddSprite(*this);
}

render_sprite::~render_sprite()
{
	render::RemoveSprite(*this);
	delete OccludedSprites;
}

void render_sprite::set(gdrv_bitmap8* bmp, zmap_header_type* zMap, int xPos, int yPos)
{
	if (Bmp == bmp && ZMap == zMap && BmpRect.XPosition == xPos && BmpRect.YPosition == yPos)
		return;

	Bmp = bmp;
	ZMap = zMap;
	DirtyFlag = VisualType != VisualTypes::Ball;
	BmpRect.XPosition = xPos;
	BmpRect.YPosition = yPos;
	if (bmp) 
	{
		BmpRect.Width = bmp->Width;
		BmpRect.Height = bmp->Height;
	}
}

void render_sprite::ball_set(gdrv_bitmap8* bmp, float depth, int xPos, int yPos)
{
	set(bmp, ZMap,xPos, yPos);
	Depth = proj::NormalizeDepth(depth);
}

void render::init(gdrv_bitmap8* bmp, int width, int height)
{
	vscreen = new gdrv_bitmap8(width, height, false);
	zscreen = new zmap_header_type(width, height, width);
	zdrv::fill(zscreen, zscreen->Width, zscreen->Height, 0, 0, 0xFFFF);
	vscreen_rect.YPosition = 0;
	vscreen_rect.XPosition = 0;
	vscreen_rect.Width = width;
	vscreen_rect.Height = height;
	vscreen->YPosition = 0;
	vscreen->XPosition = 0;
	for (auto& ballBmp : ball_bitmap)
		ballBmp = new gdrv_bitmap8(BallSaveBufferSize, BallSaveBufferSize, false);

	background_bitmap = bmp;
	if (bmp)
		gdrv::copy_bitmap(vscreen, width, height, 0, 0, bmp, 0, 0);
	else
		gdrv::fill_bitmap(vscreen, vscreen->Width, vscreen->Height, 0, 0, 0);

	recreate_screen_texture();
}

void render::uninit()
{
	delete vscreen;
	delete zscreen;

	// Sprite destructor removes it from the list.
	while (!sprite_list.empty())
		delete sprite_list[0];
	while (!ball_list.empty())
		delete ball_list[0];
	for (auto& ballBmp : ball_bitmap)
		delete ballBmp;
	DebugOverlay::UnInit();
}

void render::recreate_screen_texture()
{
	vscreen->CreateTexture(options::Options.LinearFiltering ? "linear" : "nearest", SDL_TEXTUREACCESS_STREAMING);
}

void render::update()
{
	unpaint_balls();

	// Clip dirty sprites with vScreen, clear clipping (dirty) rectangles
	for (const auto sprite : sprite_list)
	{
		if (!sprite->DirtyFlag)
			continue;

		// A hidden sprite is not drawn by anyone and has no occlude list, so
		// clearing its old damage would leave a hole rather than restore it.
		if (sprite->Hidden)
		{
			sprite->DirtyFlag = false;
			sprite->DirtyRectPrev = rectangle_type{};
			continue;
		}

		bool clearSprite = false;
		switch (sprite->VisualType)
		{
		case VisualTypes::Sprite:
			if (sprite->DirtyRectPrev.Width > 0)
				maths::enclosing_box(sprite->DirtyRectPrev, sprite->BmpRect, sprite->DirtyRect);

			if (maths::rectangle_clip(sprite->DirtyRect, vscreen_rect, &sprite->DirtyRect))
				clearSprite = true;
			else
				sprite->DirtyRect.Width = -1;
			break;
		case VisualTypes::Background:
			if (maths::rectangle_clip(sprite->BmpRect, vscreen_rect, &sprite->DirtyRect))
				clearSprite = !sprite->Bmp;
			else
				sprite->DirtyRect.Width = -1;
			break;
		default: break;
		}

		if (clearSprite)
		{
			auto yPos = sprite->DirtyRect.YPosition;
			auto width = sprite->DirtyRect.Width;
			auto xPos = sprite->DirtyRect.XPosition;
			auto height = sprite->DirtyRect.Height;
			zdrv::fill(zscreen, width, height, xPos, yPos, 0xFFFF);
			if (background_bitmap)
				gdrv::copy_bitmap(vscreen, width, height, xPos, yPos, background_bitmap, xPos, yPos);
			else
				gdrv::fill_bitmap(vscreen, width, height, xPos, yPos, 0);
		}
	}

	// Paint dirty rectangles of dirty sprites
	for (auto sprite : sprite_list)
	{
		if (!sprite->DirtyFlag || sprite->Hidden)
			continue;

		repaint(*sprite);
		sprite->DirtyFlag = false;
		sprite->DirtyRectPrev = sprite->DirtyRect;
		if (sprite->DeleteFlag)
			delete sprite;
	}

	paint_balls();
}

void render::AddSprite(render_sprite& sprite)
{
	auto& list = sprite.VisualType == VisualTypes::Ball ? ball_list : sprite_list;
	list.push_back(&sprite);
}

void render::RemoveSprite(render_sprite& sprite)
{
	auto& list = sprite.VisualType == VisualTypes::Ball ? ball_list : sprite_list;
	auto it = std::find(list.begin(), list.end(), &sprite);
	if (it != list.end())
		list.erase(it);
}

void render::set_background_zmap(zmap_header_type* zMap, int offsetX, int offsetY)
{
	background_zmap = zMap;
	zmap_offsetX = offsetX;
	zmap_offsetY = offsetY;
}

void render::repaint(const render_sprite& sprite)
{
	rectangle_type clipRect{};
	if (!sprite.OccludedSprites || sprite.VisualType == VisualTypes::Ball || sprite.DirtyRect.Width <= 0)
		return;

	for (auto refSprite : *sprite.OccludedSprites)
	{
		if (!refSprite->DeleteFlag && refSprite->Bmp && !refSprite->Hidden)
		{
			if (maths::rectangle_clip(refSprite->BmpRect, sprite.DirtyRect, &clipRect))
				zdrv::paint(
					clipRect.Width,
					clipRect.Height,
					vscreen,
					clipRect.XPosition,
					clipRect.YPosition,
					zscreen,
					clipRect.XPosition,
					clipRect.YPosition,
					refSprite->Bmp,
					clipRect.XPosition - refSprite->BmpRect.XPosition,
					clipRect.YPosition - refSprite->BmpRect.YPosition,
					refSprite->ZMap,
					clipRect.XPosition + refSprite->ZMapOffestY - refSprite->BmpRect.XPosition,
					clipRect.YPosition + refSprite->ZMapOffestX - refSprite->BmpRect.YPosition);
		}
	}
}


void render::paint_balls()
{
	// Sort ball sprites by ascending depth
	std::sort(ball_list.begin(), ball_list.end(), [](const render_sprite* lhs, const render_sprite* rhs)
	{
		return lhs->Depth < rhs->Depth;
	});

	const bool trailEnabled = options::Options.BallTrail.V;

	// Effect-ball identity. Normal keeps the classic silver sphere + trail;
	// every other kind adds a coloured (or rainbow) trail and a glow halo.
	const auto ballKind = static_cast<balleffects::Kind>(options::Options.BallKind.V);
	const auto& ballStyle = balleffects::Get(ballKind);
	const bool effectBall = ballKind != balleffects::Kind::Normal;

	// Drive the rainbow hue cycle while the ball is in play.
	GlowPhase += 0.015f;

	// For balls that clip vScreen: save original vScreen contents and paint ball bitmap.
	for (auto index = 0u; index < ball_list.size(); ++index)
	{
		auto ball = ball_list[index];
		auto dirty = &ball->DirtyRect;

		if (!ball->Bmp)
		{
			dirty->Width = -1;
			ball->TrailCount = 0;
			continue;
		}

		const auto ballX = ball->BmpRect.XPosition;
		const auto ballY = ball->BmpRect.YPosition;
		const auto ballW = ball->BmpRect.Width;
		const auto ballH = ball->BmpRect.Height;

		// Reserve a halo margin around the ball so the glow lands inside the
		// saved rectangle (and is therefore restored correctly next frame).
		const int ballRadius = std::min(ballW, ballH) / 2;
		const int glowR = effectBall
			? std::min(MaxGlowRadius, static_cast<int>(ballRadius * (1.0f + 1.1f * ballStyle.Glow) + 6.0f))
			: 0;

		// The repaint rectangle has to cover the ghosts too, otherwise the trail
		// is never restored from the background and smears across the table.
		rectangle_type paintRect = ball->BmpRect;
		for (int i = 0; i < ball->TrailCount; i++)
		{
			const auto dx = ball->TrailX[i] - ballX;
			const auto dy = ball->TrailY[i] - ballY;
			if (dx * dx + dy * dy > TrailMaxDistance * TrailMaxDistance)
				continue;

			const rectangle_type sample{ ball->TrailX[i], ball->TrailY[i], ballW, ballH };
			maths::enclosing_box(paintRect, sample, paintRect);
		}

		// Include the glow halo in the repaint rectangle so the saved region
		// covers it too (otherwise the halo would smear across the table).
		if (glowR > 0)
		{
			const rectangle_type glowBox{ ballX - glowR, ballY - glowR,
			                             ballW + 2 * glowR, ballH + 2 * glowR };
			maths::enclosing_box(paintRect, glowBox, paintRect);
		}

		// Hard limit: the save buffer must always be large enough, whatever the
		// table throws at us. The margin covers the longest trail plus the
		// widest possible glow halo.
		const rectangle_type saveLimit{
			ballX - (TrailMaxDistance + glowR), ballY - (TrailMaxDistance + glowR),
			ballW + 2 * (TrailMaxDistance + glowR), ballH + 2 * (TrailMaxDistance + glowR)
		};
		rectangle_type limited{};
		if (maths::rectangle_clip(paintRect, saveLimit, &limited))
			paintRect = limited;
		else
			paintRect = ball->BmpRect;

		if (maths::rectangle_clip(paintRect, vscreen_rect, dirty))
		{
			const auto xPos = dirty->XPosition;
			const auto yPos = dirty->YPosition;
			gdrv::copy_bitmap(ball_bitmap[index], dirty->Width, dirty->Height, 0, 0, vscreen, xPos, yPos);

			// Oldest ghost first (faintest), the solid ball is drawn last on top.
			for (int i = 0; i < ball->TrailCount; i++)
			{
				const auto dx = ball->TrailX[i] - ballX;
				const auto dy = ball->TrailY[i] - ballY;
				if (dx * dx + dy * dy > TrailMaxDistance * TrailMaxDistance)
					continue;

				const rectangle_type ghost{ ball->TrailX[i], ball->TrailY[i], ballW, ballH };
				rectangle_type clipped{};
				if (!maths::rectangle_clip(ghost, *dirty, &clipped))
					continue;

				const auto alpha = static_cast<unsigned>((i + 1) * TrailMaxAlpha / ball->TrailCount);
				// Rainbow balls advance the hue along the tail for a flowing streak.
				const float hueT = GlowPhase + static_cast<float>(i) * 0.04f;
				paint_ghost(
					clipped.Width,
					clipped.Height,
					clipped.XPosition,
					clipped.YPosition,
					clipped.XPosition - ghost.XPosition,
					clipped.YPosition - ghost.YPosition,
					vscreen,
					zscreen,
					clipped.XPosition,
					clipped.YPosition,
					ball->Bmp,
					ball->Depth,
					alpha,
					effectBall ? &ballStyle : nullptr,
					hueT);
			}

			// The dirty rect now covers the trail as well, so it can be larger than
			// the ball bitmap. paint_flat reads the source without bounds checks,
			// therefore only the intersection with the ball itself may be passed -
			// otherwise it walks off the end of the bitmap and writes garbage.
			rectangle_type ballClipped{};
			if (maths::rectangle_clip(ball->BmpRect, *dirty, &ballClipped))
			{
				if (effectBall)
				{
					// Tinted sphere for the effect balls; the classic ball keeps
					// the original bitmap verbatim.
					paint_ball(
						ballClipped.Width,
						ballClipped.Height,
						ballClipped.XPosition,
						ballClipped.YPosition,
						ballClipped.XPosition - ballX,
						ballClipped.YPosition - ballY,
						vscreen,
						zscreen,
						ballClipped.XPosition,
						ballClipped.YPosition,
						ball->Bmp,
						ball->Depth,
						&ballStyle,
						GlowPhase);
				}
				else
				{
					zdrv::paint_flat(
						ballClipped.Width,
						ballClipped.Height,
						vscreen,
						ballClipped.XPosition,
						ballClipped.YPosition,
						zscreen,
						ballClipped.XPosition,
						ballClipped.YPosition,
						ball->Bmp,
						ballClipped.XPosition - ballX,
						ballClipped.YPosition - ballY,
						ball->Depth);
				}
			}

			// Elemental halo + glowing core around the ball. Drawn after the
			// solid ball so it reads as an aura rather than a flat disc.
			if (effectBall && ballStyle.Glow > 0.0f)
			{
				uint8_t gr = ballStyle.R, gg = ballStyle.G, gb = ballStyle.B;
				if (ballStyle.Rainbow)
					balleffects::RainbowColor(GlowPhase, gr, gg, gb);
				paint_glow(ballX + ballW / 2, ballY + ballH / 2, ballRadius, glowR,
				           gr, gg, gb, ballStyle.Glow, vscreen, zscreen, ball->Depth, *dirty);
			}
		}
		else
		{
			dirty->Width = -1;
		}

		// Remember the current position so the next frame can fade it out.
		if (trailEnabled)
		{
			// Interpolate between frames: a fast ball would otherwise leave a few
			// far-apart ghosts instead of a continuous streak. One ghost per
			// TrailGhostSpacing pixels of travel keeps the spacing - and therefore
			// the length of the tail - the same no matter how fast the ball moves.
			const auto lastX = ball->TrailCount > 0 ? ball->TrailX[ball->TrailCount - 1] : ballX;
			const auto lastY = ball->TrailCount > 0 ? ball->TrailY[ball->TrailCount - 1] : ballY;
			const auto stepX = ballX - lastX;
			const auto stepY = ballY - lastY;
			const auto stepDist = std::sqrt(static_cast<double>(stepX * stepX + stepY * stepY));

			if (stepX == 0 && stepY == 0)
			{
				// Ball at rest - the existing ghosts already sit on top of it, so
				// there is nothing to add and no point re-blitting them.
				continue;
			}

			auto steps = static_cast<int>(stepDist / TrailGhostSpacing) + 1;
			if (steps > TrailMaxSteps)
				steps = TrailMaxSteps;

			for (auto s = 1; s <= steps; s++)
			{
				if (ball->TrailCount == render_sprite::TrailCapacity)
				{
					for (int i = 1; i < ball->TrailCount; i++)
					{
						ball->TrailX[i - 1] = ball->TrailX[i];
						ball->TrailY[i - 1] = ball->TrailY[i];
					}
					ball->TrailCount--;
				}

				ball->TrailX[ball->TrailCount] = lastX + stepX * s / steps;
				ball->TrailY[ball->TrailCount] = lastY + stepY * s / steps;
				ball->TrailCount++;
			}
		}
		else
		{
			ball->TrailCount = 0;
		}
	}
}

bool render::SaveScreenshot(const char* path)
{
	int width, height;
	if (SDL_GetRendererOutputSize(winmain::Renderer, &width, &height) != 0 || width <= 0 || height <= 0)
		return false;

	auto* surface = SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, SDL_PIXELFORMAT_ARGB8888);
	if (!surface)
		return false;

	auto saved = false;
	if (SDL_RenderReadPixels(winmain::Renderer, nullptr, SDL_PIXELFORMAT_ARGB8888,
	                         surface->pixels, surface->pitch) == 0)
	{
		saved = SDL_SaveBMP(surface, path) == 0;
	}

	SDL_FreeSurface(surface);
	return saved;
}

void render::unpaint_balls()
{
	// Restore portions of vScreen saved during previous paint_balls call.
	for (int index = static_cast<int>(ball_list.size()) - 1; index >= 0; index--)
	{
		auto curBall = ball_list[index];
		if (curBall->DirtyRect.Width > 0)
			gdrv::copy_bitmap(
				vscreen,
				curBall->DirtyRect.Width,
				curBall->DirtyRect.Height,
				curBall->DirtyRect.XPosition,
				curBall->DirtyRect.YPosition,
				ball_bitmap[index],
				0,
				0);

		curBall->DirtyRectPrev = curBall->DirtyRect;
	}
}

void render::shift(int offsetX, int offsetY){
	offset_x += offsetX;
	offset_y += offsetY;
}

void render::build_occlude_list()
{
	std::vector<render_sprite*>* spriteArr = nullptr;
	for (auto mainSprite : sprite_list)
	{
		if (mainSprite->OccludedSprites)
		{
			delete mainSprite->OccludedSprites;
			mainSprite->OccludedSprites = nullptr;
		}

		if (!mainSprite->DeleteFlag && !mainSprite->Hidden && mainSprite->BoundingRect.Width != -1)
		{
			if (!spriteArr)
				spriteArr = new std::vector<render_sprite*>();

			for (auto refSprite : sprite_list)
			{
				if (!refSprite->DeleteFlag && !refSprite->Hidden
					&& refSprite->BoundingRect.Width != -1
					&& maths::rectangle_clip(mainSprite->BoundingRect, refSprite->BoundingRect, nullptr))
				{
					spriteArr->push_back(refSprite);
				}
			}

			if (mainSprite->Bmp && spriteArr->size() < 2)
				spriteArr->clear();
			if (!spriteArr->empty())
			{
				mainSprite->OccludedSprites = spriteArr;
				spriteArr = nullptr;
			}
		}
	}

	delete spriteArr;
}

void render::InvalidateAll(bool resetDepth)
{
	if (!vscreen || !zscreen)
		return;

	if (resetDepth)
	{
		// Nothing on screen is valid any more: every sprite has to be able to
		// overwrite the depth values the old arrangement left behind.
		zdrv::fill(zscreen, zscreen->Width, zscreen->Height, 0, 0, 0xFFFF);
	}

	for (auto sprite : sprite_list)
	{
		// An empty previous rectangle makes the sprite report its whole area as
		// damaged, so the background and everything on it are repainted.
		sprite->DirtyRectPrev = rectangle_type{};

		if (sprite->VisualType == VisualTypes::Ball)
			continue;

		if (sprite->Hidden)
		{
			sprite->DirtyFlag = false;
			continue;
		}

		sprite->DirtyFlag = true;
		// Left alone, update() would keep the damage rectangle it computed for
		// the previous frame, which after a move is somewhere else entirely.
		if (resetDepth)
			sprite->DirtyRect = sprite->BmpRect;
	}

	if (resetDepth)
	{
		// The ball save buffers hold pixels copied out of the old frame, so
		// restoring them on the next unpaint would smear it back in.
		for (auto ball : ball_list)
		{
			ball->DirtyRect.Width = -1;
			ball->DirtyRectPrev = rectangle_type{};
			ball->TrailCount = 0;
		}
	}

	// The depth buffer is otherwise deliberately left alone: only colours
	// changed, so the existing depth values are still valid.
}

void render::SpriteViewer(bool* show)
{
	static const char* BitmapTypes[] =
	{
		"None",
		"RawBitmap",
		"DibBitmap",
		"Spliced",
	};
	static float scale = 1.0f;
	auto uv_min = ImVec2(0.0f, 0.0f); // Top-left
	auto uv_max = ImVec2(1.0f, 1.0f); // Lower-right
	auto tint_col = ImVec4(1.0f, 1.0f, 1.0f, 1.0f); // No tint
	auto border_col = ImVec4(1.0f, 1.0f, 1.0f, 0.5f); // 50% opaque white

	if (ImGui::Begin("Sprite viewer", show, ImGuiWindowFlags_HorizontalScrollbar | ImGuiWindowFlags_MenuBar))
	{
		if (ImGui::BeginMenuBar())
		{
			ImGui::SliderFloat("Sprite scale", &scale, 0.1f, 10.0f, "scale = %.3f");
			ImGui::EndMenuBar();
		}

		for (const auto group : pb::record_table->Groups)
		{
			bool emptyGroup = true;
			for (int i = 0; i <= 2; i++)
			{
				auto bmp = group->GetBitmap(i);
				if (bmp)
				{
					emptyGroup = false;
					break;
				}
			}
			if (emptyGroup)
				continue;

			ImGui::Text("Group: %d, name:%s", group->GroupId, group->GroupName.c_str());
			for (int i = 0; i <= 2; i++)
			{
				auto bmp = group->GetBitmap(i);
				if (!bmp)
					continue;

				auto type = BitmapTypes[static_cast<uint8_t>(bmp->BitmapType)];
				ImGui::Text("type:%s, size:%d, resolution: %dx%d, offset:%dx%d", type,
				            bmp->Resolution,
				            bmp->Width, bmp->Height, bmp->XPosition, bmp->YPosition);
			}

			for (int same = 0, i = 0; i <= 2; i++)
			{
				auto bmp = group->GetBitmap(i);
				if (!bmp)
					continue;

				gdrv::CreatePreview(*bmp);
				if (bmp->Texture)
				{
					if (!same)
						same = true;
					else
						ImGui::SameLine();

					ImGui::Image(bmp->Texture, ImVec2(bmp->Width * scale, bmp->Height * scale),
					             uv_min, uv_max, tint_col, border_col);
				}
			}

			for (int same = 0, i = 0; i <= 2; i++)
			{
				auto zMap = group->GetZMap(i);
				if (!zMap)
					continue;

				zdrv::CreatePreview(*zMap);
				if (zMap->Texture)
				{
					if (!same)
						same = true;
					else
						ImGui::SameLine();
					ImGui::Image(zMap->Texture, ImVec2(zMap->Width * scale, zMap->Height * scale),
					             uv_min, uv_max, tint_col, border_col);
				}
			}
		}
	}
	ImGui::End();
}

void render::PresentVScreen()
{
	vscreen->BlitToTexture();

	// The scoreboard column the .DAT reserves on the right is never shown: the
	// score lives in the toolbar drawn over the top of the table instead.
	// Clipping the source here is what hands that wasted part of the canvas
	// back to the playfield, and it works for every skin without touching the
	// artwork or the depth map.
	const auto tableWidth = fullscrn::GetTableWidth();
	SDL_Rect srcRect{ 0, 0, tableWidth, vscreen->Height };
	if (tableWidth <= 0 || tableWidth >= vscreen->Width)
		srcRect.w = vscreen->Width;

	// Nudging still has to shake the board, so the offset goes on the
	// destination rect instead; there is no sidebar left that must stay put.
	SDL_Rect dstRect = DestinationRect;
	if (offset_x != 0 || offset_y != 0)
	{
		dstRect.x += static_cast<int>(lround(offset_x * fullscrn::ScaleX));
		dstRect.y += static_cast<int>(lround(offset_y * fullscrn::ScaleY));
	}

	SDL_RenderCopy(winmain::Renderer, vscreen->Texture, &srcRect, &dstRect);

	if (options::Options.DebugOverlay)
	{
		DebugOverlay::DrawOverlay();
	}
}
