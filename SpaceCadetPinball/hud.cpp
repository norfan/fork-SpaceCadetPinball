#include "pch.h"
#include "hud.h"

#include <algorithm>
#include <cmath>

#include "imgui.h"
#include "options.h"
#include "pb.h"
#include "score.h"
#include "tabletheme.h"
#include "translations.h"
#include "TPinballTable.h"
#include "balleffects.h"

namespace
{
	ImFont* bigFont = nullptr;
	float bigFontSize = 30.0f;

	int lastScore = -1;

	// Set to 1.0 whenever the score climbs, then decays. Drives the "punch"
	// zoom on the live score readout so the digit jump is unmistakable.
	float scorePulse = 0.0f;

	struct ScorePop
	{
		int Amount;
		float Age;
	};

	std::vector<ScorePop> scorePops;
	constexpr float PopLife = 1.1f;
	constexpr int MaxPops = 8;

	// Labels are the only translated strings in the toolbar. The playfield
	// numerals are plain digits, so the oversized font can stay Latin-only and
	// the glyph atlas stays small.
	const char* ballLabel()
	{
		return translations::GetCurrentLanguage()->Language == Lang::SimplifiedChinese ? "球" : "BALL";
	}

	const char* playerLabel()
	{
		return translations::GetCurrentLanguage()->Language == Lang::SimplifiedChinese ? "玩家" : "PLAYER";
	}

	void draw_text(ImDrawList* list, ImFont* font, float size, const ImVec2& pos, ImU32 color, const char* text)
	{
		// A drop shadow is what keeps the numerals readable on top of the
		// brighter parts of the artwork; no panel is drawn behind them.
		list->AddText(font, size, ImVec2(pos.x + 1.0f, pos.y + 2.0f), IM_COL32(0, 0, 0, 170), text);
		list->AddText(font, size, pos, color, text);
	}

	// Crisp text on top of a cheap bloom: the glyphs are stamped a few pixels
	// out in a low-alpha glow colour, then redrawn sharp, so a "+N" marker
	// reads as lit rather than merely coloured.
	void draw_text_glow(ImDrawList* list, ImFont* font, float size, const ImVec2& pos,
	                    ImU32 color, ImU32 glow, const char* text)
	{
		for (int oy = -2; oy <= 2; ++oy)
		{
			for (int ox = -2; ox <= 2; ++ox)
			{
				if (ox == 0 && oy == 0)
					continue;
				list->AddText(font, size, ImVec2(pos.x + static_cast<float>(ox), pos.y + static_cast<float>(oy)), glow, text);
			}
		}
		list->AddText(font, size, pos, color, text);
	}

	float ease_out_back(float t)
	{
		constexpr float c1 = 1.70158f, c3 = c1 + 1.0f;
		const float p = t - 1.0f;
		return 1.0f + c3 * p * p * p + c1 * p * p;
	}

	float text_width(ImFont* font, float size, const char* text)
	{
		return font->CalcTextSizeA(size, FLT_MAX, 0.0f, text).x;
	}
}

void hud::InitFont()
{
	ImGuiIO& io = ImGui::GetIO();

	// Baked larger than it is drawn: shrinking a glyph keeps it sharp, growing
	// one blurs it, so the atlas has to hold the biggest size that will ever be
	// needed and the draw call scales down from there.
	const auto bakedSize = 46.0f * std::max(1.0f, options::Options.UIScale.V);

	ImFont* font = nullptr;
	if (!options::Options.FontFileName.V.empty())
		font = io.Fonts->AddFontFromFileTTF(options::Options.FontFileName.V.c_str(), bakedSize);

	if (!font)
	{
		// No configured UI font: borrow a system one so the score is not stuck
		// at the 13px bitmap font the menus fall back to.
		static const char* const Candidates[] =
		{
			"C:/Windows/Fonts/consolab.ttf",
			"C:/Windows/Fonts/seguisb.ttf",
			"C:/Windows/Fonts/arialbd.ttf",
			"/System/Library/Fonts/Supplemental/Arial Bold.ttf",
			"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
		};
		for (auto path : Candidates)
		{
			font = io.Fonts->AddFontFromFileTTF(path, bakedSize);
			if (font)
				break;
		}
	}

	if (!font)
		font = io.Fonts->AddFontDefault();

	bigFont = font;
	bigFontSize = bakedSize;
}

void hud::Reset()
{
	lastScore = -1;
	scorePops.clear();
}

void hud::Draw()
{
	auto* table = pb::MainTable;
	if (!table)
		return;

	ImDrawList* list = ImGui::GetBackgroundDrawList();
	const ImGuiIO& io = ImGui::GetIO();

	// Everything scales with the window so the toolbar keeps its proportions
	// when the playfield is enlarged.
	const auto scale = std::max(1.0f, io.DisplaySize.y / 666.0f);
	const auto top = ImGui::GetFrameHeight();
	const auto barHeight = 46.0f * scale;
	const auto pad = 18.0f * scale;
	const auto uiFont = ImGui::GetFont();
	const auto uiSize = ImGui::GetFontSize();

	// Scrim: dense behind the numerals, gone by the bottom edge, so the art
	// still reads as the background.
	list->AddRectFilledMultiColor(
		ImVec2(0.0f, top),
		ImVec2(io.DisplaySize.x, top + barHeight),
		IM_COL32(3, 7, 16, 210), IM_COL32(3, 7, 16, 210),
		IM_COL32(3, 7, 16, 0), IM_COL32(3, 7, 16, 0));
	list->AddLine(ImVec2(0.0f, top + barHeight), ImVec2(io.DisplaySize.x, top + barHeight),
	              IM_COL32(120, 200, 255, 28), std::max(1.0f, scale));

	const auto score = table->CurScore;
	char scoreText[48]{};
	score::string_format(score, scoreText);
	if (scoreText[0] == 0)
		snprintf(scoreText, sizeof scoreText, "0");
	if (table->CurScoreE9 > 0)
	{
		char millions[64]{};
		snprintf(millions, sizeof millions, "%d,%09d", static_cast<int>(table->CurScoreE9), score);
		memcpy(scoreText, millions, sizeof scoreText - 1);
		scoreText[sizeof scoreText - 1] = 0;
	}

	// Floating "+N" markers. They only ever move upwards and fade, so they
	// never fight with the live score for the same pixels.
	if (lastScore >= 0 && score > lastScore)
	{
		scorePulse = 1.0f;  // kick the live-score zoom
		if (static_cast<int>(scorePops.size()) >= MaxPops)
			scorePops.erase(scorePops.begin());
		scorePops.push_back({score - lastScore, 0.0f});
	}
	else if (lastScore >= 0 && score < lastScore)
	{
		scorePops.clear();
	}
	lastScore = score;

	// Decay the zoom pulse.
	scorePulse = std::max(0.0f, scorePulse - io.DeltaTime * 3.2f);

	const auto drawSize = std::min(bigFontSize, 30.0f * scale);
	// Punchy zoom on score gain: overshoots a touch then settles back.
	const auto pulsedSize = drawSize * (1.0f + 0.35f * scorePulse);
	const auto scorePos = ImVec2(pad, top + 12.0f * scale);
	draw_text(list, uiFont, uiSize,
	          ImVec2(pad, top + 1.5f * scale), IM_COL32(150, 205, 240, 190),
	          pb::get_rc_string(Msg::HIGHSCORES_Score));
	draw_text(list, bigFont, pulsedSize, scorePos, IM_COL32(226, 244, 255, 245), scoreText);

	const auto scoreWidth = text_width(bigFont, pulsedSize, scoreText);

	// The accent colour of the floating markers tracks the current ball kind,
	// tying the scoring feedback to the ball the player is launching.
	const auto ballKind = static_cast<balleffects::Kind>(options::Options.BallKind.V);
	const bool effOn = ballKind != balleffects::Kind::Normal;
	const auto& effStyle = balleffects::Get(ballKind);
	const ImU32 popColor = effOn ? IM_COL32(effStyle.R, effStyle.G, effStyle.B, 255)
	                             : IM_COL32(150, 255, 190, 255);
	const ImU32 popGlow = effOn ? IM_COL32(effStyle.R, effStyle.G, effStyle.B, 80)
	                            : IM_COL32(80, 235, 150, 80);

	for (auto& pop : scorePops)
	{
		pop.Age += io.DeltaTime;
		const auto life = 1.0f - std::min(1.0f, pop.Age / PopLife);
		if (life <= 0.0f)
			continue;

		char popText[48]{};
		char amount[32]{};
		score::string_format(pop.Amount, amount);
		snprintf(popText, sizeof popText, "+%s", amount);

		// Bouncy rise (overshoots via ease-out-back) and a scale pop at birth.
		const auto progress = 1.0f - life;
		const auto rise = ease_out_back(progress) * 34.0f * scale;
		const auto popSize = drawSize * (0.62f + 0.33f * life);
		draw_text_glow(list, bigFont, popSize,
		               ImVec2(pad + scoreWidth + 16.0f * scale, scorePos.y + 2.0f * scale + rise),
		               popColor, popGlow, popText);
	}

	scorePops.erase(std::remove_if(scorePops.begin(), scorePops.end(),
	                               [](const ScorePop& pop) { return pop.Age >= PopLife; }),
	                scorePops.end());

	// Ball counter and player number, right aligned.
	char right[64]{};
	snprintf(right, sizeof right, "%s %d/%d    %s %d",
	         ballLabel(), std::max(0, table->BallCount), std::max(1, table->MaxBallCount),
	         playerLabel(), table->CurrentPlayer + 1);
	draw_text(list, uiFont, uiSize,
	          ImVec2(io.DisplaySize.x - pad - text_width(uiFont, uiSize, right), top + 20.0f * scale),
	          IM_COL32(190, 225, 250, 220), right);

	// Skin name dead centre, understated: the artwork already carries the
	// identity, this is only a caption for the layout that is loaded.
	const auto theme = tabletheme::CurrentName();
	const auto caption = theme.empty() ? "STOCK" : theme.c_str();
	draw_text(list, uiFont, uiSize,
	          ImVec2((io.DisplaySize.x - text_width(uiFont, uiSize, caption)) * 0.5f, top + 20.0f * scale),
	          IM_COL32(130, 175, 215, 170), caption);
}
