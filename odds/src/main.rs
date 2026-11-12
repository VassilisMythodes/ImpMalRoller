//! d100 Test odds: exact Success Level, Critical and Fumble chances for Unopposed and Opposed Tests, same rules as ../rolls.py.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")] // no console window in release builds

use eframe::egui::{self, Color32, DragValue};
use egui_plot::{AxisHints, Bar, BarChart, Legend, Line, Plot, VLine, uniform_grid_spacer};
use std::{cmp::Ordering, collections::BTreeMap};

const BLUE: Color32 = Color32::from_rgb(60, 120, 230);
const RED: Color32 = Color32::from_rgb(220, 60, 50);
const GOLD: Color32 = Color32::from_rgb(240, 180, 40);
const PURPLE: Color32 = Color32::from_rgb(150, 80, 200);

/// One side of a Test. Negative `adv` is Disadvantage (the two cancel 1:1).
#[derive(Clone, Copy, PartialEq)]
struct Side {
    skill: i32,
    flat: i32,
    sl: i32,
    adv: i32,
}

/// One side's result. A double (11, 22 ... 99, and 100) is a Critical if it succeeds and a Fumble if it fails.
#[derive(Clone, Copy)]
struct Roll {
    sl: i32,
    success: bool,
    double: bool,
}

impl Side {
    /// Skill plus flat modifier, then ±10 per Advantage (Disadvantage) after the first.
    fn target(&self) -> i32 {
        self.skill + self.flat + 10 * (self.adv.abs() - 1).max(0) * self.adv.signum()
    }

    /// The result of a d100 roll of 1..=100, where 100 is "00".
    fn resolve(&self, rolled: i32) -> Roll {
        // Swapped dice: 93 -> 39, 10 -> 01, 01 -> 10, and 100 ("00" + "0") stays 100.
        let swapped = match rolled % 10 * 10 + rolled / 10 % 10 {
            0 => 100,
            r => r,
        };
        // Lower is never worse: Advantage swaps if that is better, Disadvantage must if it is worse.
        let roll = match self.adv.signum() {
            1 => rolled.min(swapped),
            -1 => rolled.max(swapped),
            _ => rolled,
        };
        let target = self.target();
        // Difference in tens digits; a roll of 100 has 10 tens.
        let sl = target.div_euclid(10) - roll / 10;
        // Swapping never makes or breaks a double.
        let double = rolled % 10 == rolled / 10 % 10;
        // An SL modifier can flip the result, and landing on 0 is a +0 success.
        let (sl, success) = if self.sl == 0 { (sl, roll <= target) } else { (sl + self.sl, sl + self.sl >= 0) };
        Roll { sl, success, double }
    }
}

/// Chance of an outcome, and of it coming with a Critical or a Fumble by [you, the opponent].
#[derive(Clone, Copy, Default)]
struct Chance {
    all: f64,
    crit: [f64; 2],
    fumble: [f64; 2],
}

impl Chance {
    fn add(&mut self, weight: f64, rolls: &[Roll]) {
        self.all += weight;
        for (side, r) in rolls.iter().enumerate() {
            if r.double {
                let doubles = if r.success { &mut self.crit } else { &mut self.fumble };
                doubles[side] += weight;
            }
        }
    }
}

/// Outcome key, higher is better for you: +n SL is n + 1, -n SL is -(n + 1), and a tie is 0.
fn key(win: bool, sl: i32) -> i32 {
    if win { sl.abs() + 1 } else { -sl.abs() - 1 }
}

/// Opposed Test: the higher SL wins by the difference, and at equal SL +0 still beats -0.
fn versus(a: Roll, b: Roll) -> i32 {
    match (a.sl, a.success).cmp(&(b.sl, b.success)) {
        Ordering::Greater => key(true, a.sl - b.sl),
        Ordering::Less => key(false, a.sl - b.sl),
        Ordering::Equal => 0,
    }
}

/// Exact chance of each outcome key, over all 100 rolls (100 × 100 if opposed).
fn outcomes(i: &Inputs) -> BTreeMap<i32, Chance> {
    let rolls = |s: Side| (1..=100).map(move |r| s.resolve(r));
    let mut chances = BTreeMap::<i32, Chance>::new();
    if i.opposed {
        for a in rolls(i.you) {
            for b in rolls(i.opp) {
                chances.entry(versus(a, b)).or_default().add(1e-4, &[a, b]);
            }
        }
    } else {
        for a in rolls(i.you) {
            chances.entry(key(a.success, a.sl)).or_default().add(0.01, &[a]);
        }
    }
    chances
}

/// [you win (succeed), tie, opponent wins (fail)]
fn split(chances: &BTreeMap<i32, Chance>) -> [f64; 3] {
    let sum = |range| chances.range(range).map(|(_, c)| c.all).sum::<f64>();
    [sum(1..=i32::MAX), sum(0..=0), sum(i32::MIN..=-1)]
}

/// All outcomes together, so each side's overall Critical and Fumble chances.
fn total(chances: &BTreeMap<i32, Chance>) -> Chance {
    let mut t = Chance::default();
    for c in chances.values() {
        t.all += c.all;
        for side in 0..2 {
            t.crit[side] += c.crit[side];
            t.fumble[side] += c.fumble[side];
        }
    }
    t
}

fn outcome_name(k: i32) -> String {
    match k.signum() {
        1 => format!("+{} SL", k - 1),
        -1 => format!("-{} SL", -k - 1),
        _ => "Tie".into(),
    }
}

fn adv_name(a: i32) -> String {
    match a.signum() {
        1 => format!("{a} Advantage"),
        -1 => format!("{} Disadvantage", -a),
        _ => "None".into(),
    }
}

fn pct(p: f64) -> String {
    format!("{:.2}%", 100.0 * p)
}

#[derive(Clone, Copy, PartialEq)]
enum Field {
    Sl,
    Flat,
    Adv,
}

/// A modifier of either side to vary, 3 steps either way.
#[derive(Clone, Copy, PartialEq)]
struct Knob {
    opponent: bool,
    field: Field,
}

impl Knob {
    fn name(self) -> String {
        let field = match self.field {
            Field::Sl => "SL modifier",
            Field::Flat => "flat modifier",
            Field::Adv => "Advantage",
        };
        format!("{} {field}", if self.opponent { "Opponent's" } else { "Your" })
    }

    fn get(self, i: &mut Inputs) -> &mut i32 {
        let s = if self.opponent { &mut i.opp } else { &mut i.you };
        match self.field {
            Field::Sl => &mut s.sl,
            Field::Flat => &mut s.flat,
            Field::Adv => &mut s.adv,
        }
    }

    fn of(self, mut i: Inputs) -> i32 {
        *self.get(&mut i)
    }

    /// 1 SL, 10 points of flat modifier, or 1 Advantage.
    fn step(self) -> i32 {
        if self.field == Field::Flat { 10 } else { 1 }
    }

    fn show(self, v: i32) -> String {
        if self.field == Field::Adv { adv_name(v) } else { format!("{v:+}") }
    }
}

#[derive(Clone, Copy, PartialEq)]
struct Inputs {
    opposed: bool,
    you: Side,
    opp: Side,
    vary: Option<Knob>,
}

impl Default for Inputs {
    fn default() -> Self {
        // The example from the brief: you at 45 against 55 with +2 SL and Advantage.
        let you = Side { skill: 45, flat: 0, sl: 0, adv: 0 };
        Inputs { opposed: true, you, opp: Side { skill: 55, sl: 2, adv: 1, ..you }, vary: None }
    }
}

/// Everything shown, computed once per click on Generate.
struct Results {
    inputs: Inputs,
    chances: BTreeMap<i32, Chance>,
    /// (value of the varied modifier, split, totals) when one is varied.
    sweep: Vec<(i32, [f64; 3], Chance)>,
    table: Vec<Vec<String>>,
}

impl Results {
    fn new(inputs: Inputs) -> Self {
        let chances = outcomes(&inputs);
        let opposed = inputs.opposed;
        let cells = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        // Critical and Fumble columns: yours, then the opponent's. Blank means it never happens.
        let doubles_header = if opposed { cells(&["You crit", "You fumble", "Opponent crits", "Opponent fumbles"]) } else { cells(&["Critical", "Fumble"]) };
        let doubles = |c: &Chance| {
            let ps = if opposed { vec![c.crit[0], c.fumble[0], c.crit[1], c.fumble[1]] } else { vec![c.crit[0], c.fumble[0]] };
            ps.into_iter().map(|p| if p == 0.0 { String::new() } else { pct(p) }).collect::<Vec<_>>()
        };
        let (sweep, table) = match inputs.vary {
            None => {
                let header = cells(&[if opposed { "Your net SL" } else { "Your SL" }, "Chance", "This or better"]);
                let mut table = vec![[header, doubles_header].concat()];
                let mut better = 0.0;
                for (&k, c) in chances.iter().rev() {
                    better += c.all;
                    table.push([vec![outcome_name(k), pct(c.all), pct(better)], doubles(c)].concat());
                }
                (vec![], table)
            }
            Some(knob) => {
                let now = knob.of(inputs);
                let sweep: Vec<_> = (-3..=3)
                    .map(|d| {
                        let mut i = inputs;
                        *knob.get(&mut i) = now + d * knob.step();
                        let chances = outcomes(&i);
                        (now + d * knob.step(), split(&chances), total(&chances))
                    })
                    .collect();
                let name = knob.name();
                let header = if opposed { cells(&[name.as_str(), "You win", "Tie", "Opponent wins"]) } else { cells(&[name.as_str(), "Success"]) };
                let mut table = vec![[header, doubles_header].concat()];
                for (v, [win, tie, lose], t) in &sweep {
                    let name = knob.show(*v) + if *v == now { " (current)" } else { "" };
                    let odds = if opposed { vec![name, pct(*win), pct(*tie), pct(*lose)] } else { vec![name, pct(*win)] };
                    table.push([odds, doubles(t)].concat());
                }
                (sweep, table)
            }
        };
        Results { inputs, chances, sweep, table }
    }
}

struct App {
    inputs: Inputs,
    results: Results,
}

impl App {
    /// The default inputs, already generated.
    fn new() -> Self {
        let inputs = Inputs::default();
        App { inputs, results: Results::new(inputs) }
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _: &mut eframe::Frame) {
        egui::Panel::left("inputs").show(ui, |ui| {
            let i = &mut self.inputs;
            ui.checkbox(&mut i.opposed, "Opposed Test");
            ui.heading("You");
            side_ui(ui, "you", &mut i.you);
            if i.opposed {
                ui.heading("Opponent");
                side_ui(ui, "opponent", &mut i.opp);
            } else if i.vary.is_some_and(|k| k.opponent) {
                i.vary = None; // no opponent to vary
            }
            ui.separator();
            ui.horizontal(|ui| {
                ui.label("Vary");
                egui::ComboBox::from_id_salt("vary").selected_text(i.vary.map_or("Nothing".into(), Knob::name)).show_ui(ui, |ui| {
                    ui.selectable_value(&mut i.vary, None, "Nothing");
                    let sides: &[bool] = if i.opposed { &[false, true] } else { &[false] };
                    for &opponent in sides {
                        for field in [Field::Sl, Field::Flat, Field::Adv] {
                            let k = Knob { opponent, field };
                            ui.selectable_value(&mut i.vary, Some(k), k.name());
                        }
                    }
                });
            });
            if ui.button("Generate").clicked() {
                self.results = Results::new(self.inputs);
            }
            if self.inputs != self.results.inputs {
                ui.weak("Inputs changed: click Generate.");
            }
        });
        egui::CentralPanel::default().show(ui, |ui| egui::ScrollArea::vertical().show(ui, |ui| results_ui(ui, &self.results)));
    }
}

fn side_ui(ui: &mut egui::Ui, id: &str, s: &mut Side) {
    egui::Grid::new(id).num_columns(2).show(ui, |ui| {
        ui.label("Skill");
        ui.add(DragValue::new(&mut s.skill).range(0..=999));
        ui.end_row();
        ui.label("Flat modifier");
        ui.add(DragValue::new(&mut s.flat).range(-999..=999).custom_formatter(|v, _| format!("{v:+}")));
        ui.end_row();
        ui.label("SL modifier");
        ui.add(DragValue::new(&mut s.sl).range(-99..=99).speed(0.05).custom_formatter(|v, _| format!("{v:+}")));
        ui.end_row();
        ui.label("Advantage");
        ui.add(DragValue::new(&mut s.adv).range(-9..=9).speed(0.05).custom_formatter(|v, _| adv_name(v as i32)))
            .on_hover_text("Negative is Disadvantage");
        ui.end_row();
        ui.label("Target");
        ui.label(s.target().to_string());
        ui.end_row();
    });
}

/// One layer of the stacked outcome bars: 0 your Critical, 1 your Fumble, 2 the rest, for the outcomes `keep` picks.
fn layer(chances: &BTreeMap<i32, Chance>, n: usize, keep: fn(i32) -> bool) -> Vec<Bar> {
    let mut bars = vec![];
    for (&k, c) in chances.iter().filter(|e| keep(*e.0)) {
        let parts = [c.crit[0], c.fumble[0], c.all - c.crit[0] - c.fumble[0]];
        if parts[n] > 0.0 {
            // The hover text: the rest's bar names the whole outcome.
            let name = match n {
                0 => format!("{} with your Critical: {}", outcome_name(k), pct(parts[0])),
                1 => format!("{} with your Fumble: {}", outcome_name(k), pct(parts[1])),
                _ => format!("{}: {}", outcome_name(k), pct(c.all)),
            };
            bars.push(Bar::new(k as f64, 100.0 * parts[n]).base_offset(100.0 * parts[..n].iter().sum::<f64>()).name(name));
        }
    }
    bars
}

fn results_ui(ui: &mut egui::Ui, r: &Results) {
    let i = &r.inputs;
    let [win, tie, lose] = split(&r.chances);
    let t = total(&r.chances);
    if i.opposed {
        ui.heading(format!("You win {} · Tie {} · Opponent wins {}", pct(win), pct(tie), pct(lose)));
        ui.label(format!(
            "Critical: you {}, opponent {} · Fumble: you {}, opponent {}",
            pct(t.crit[0]),
            pct(t.crit[1]),
            pct(t.fumble[0]),
            pct(t.fumble[1])
        ));
    } else {
        ui.heading(format!("Success {} · Failure {}", pct(win), pct(lose)));
        ui.label(format!("Critical {} · Fumble {}", pct(t.crit[0]), pct(t.fumble[0])));
    }

    let (good, bad) = if i.opposed { ("You win", "Opponent wins") } else { ("Success", "Failure") };
    let plot = Plot::new("plot")
        .height(320.0)
        .legend(Legend::default())
        .y_axis_label("Chance (%)")
        .allow_drag(false)
        .allow_zoom(false)
        .allow_scroll(false)
        .allow_boxed_zoom(false);
    match i.vary {
        None => {
            let chart = |name: &str, color: Color32, bars: Vec<Bar>| {
                BarChart::new(name, bars).color(color).width(0.8).element_formatter(Box::new(|b, _| b.name.clone()))
            };
            let solid = |bars: Vec<Bar>, color: Color32| bars.into_iter().map(|b| b.fill(color)).collect::<Vec<_>>();
            // One tick per outcome present: "-2", "-0", "Tie", "+0", "+3"...
            let x_axis = AxisHints::new_x()
                .label(if i.opposed { "Your net SL" } else { "Your SL" })
                .label_spacing(24.0..=32.0)
                .formatter(|m, _| match m.value.fract() == 0.0 && r.chances.contains_key(&(m.value as i32)) {
                    true => outcome_name(m.value as i32).replace(" SL", ""),
                    false => String::new(),
                });
            let top = r.chances.values().fold(0.0, |a: f64, c| a.max(c.all));
            let plot = plot.include_y(130.0 * top); // headroom so the legend clears the bars
            plot.custom_x_axes(vec![x_axis]).x_grid_spacer(uniform_grid_spacer(|_| [1.0, 5.0, 10.0])).show(ui, |p| {
                p.bar_chart(chart(bad, RED, layer(&r.chances, 2, |k| k < 0)));
                if i.opposed {
                    p.bar_chart(chart("Tie", Color32::GRAY, layer(&r.chances, 2, |k| k == 0)));
                }
                p.bar_chart(chart(good, BLUE, layer(&r.chances, 2, |k| k > 0)));
                p.bar_chart(chart("Your Critical", GOLD, solid(layer(&r.chances, 0, |_| true), GOLD)));
                p.bar_chart(chart("Your Fumble", PURPLE, solid(layer(&r.chances, 1, |_| true), PURPLE)));
            });
        }
        Some(knob) => {
            let line = |n: usize| r.sweep.iter().map(|&(v, s, _)| [v as f64, 100.0 * s[n]]).collect::<Vec<_>>();
            let ticks = move |m: egui_plot::GridMark, _: &_| if m.value.fract() == 0.0 { knob.show(m.value as i32) } else { String::new() };
            plot.x_axis_label(knob.name()).x_axis_formatter(ticks).include_y(0.0).include_y(100.0).show(ui, |p| {
                p.vline(VLine::new("Current", knob.of(*i)).color(Color32::GRAY));
                p.line(Line::new(good, line(0)).color(BLUE).width(2.0));
                if i.opposed {
                    p.line(Line::new(bad, line(2)).color(RED).width(2.0));
                }
            });
        }
    }

    ui.horizontal(|ui| {
        ui.strong("Table");
        if ui.button("Copy").on_hover_text("Tab-separated: pastes into spreadsheets").clicked() {
            ui.ctx().copy_text(r.table.iter().map(|row| row.join("\t")).collect::<Vec<_>>().join("\n"));
        }
    });
    egui::Grid::new("table").striped(true).show(ui, |ui| {
        for (n, row) in r.table.iter().enumerate() {
            for cell in row {
                if n == 0 { ui.strong(cell) } else { ui.label(cell) };
            }
            ui.end_row();
        }
    });
}

/// Desktop: a native window.
#[cfg(not(target_arch = "wasm32"))]
fn main() -> eframe::Result {
    let options = eframe::NativeOptions { viewport: egui::ViewportBuilder::default().with_inner_size([1000.0, 760.0]), ..Default::default() };
    eframe::run_native("d100 Test Odds", options, Box::new(|_| Ok(Box::new(App::new()))))
}

/// Browser (built with Trunk): the same app, drawn on the canvas in index.html.
#[cfg(target_arch = "wasm32")]
fn main() {
    use eframe::wasm_bindgen::JsCast as _;

    wasm_bindgen_futures::spawn_local(async {
        let document = web_sys::window().and_then(|w| w.document()).expect("no document");
        let canvas = document.get_element_by_id("the_canvas_id").and_then(|e| e.dyn_into::<web_sys::HtmlCanvasElement>().ok());
        let canvas = canvas.expect("index.html has no <canvas id=\"the_canvas_id\">");
        let started = eframe::WebRunner::new().start(canvas, eframe::WebOptions::default(), Box::new(|_| Ok(Box::new(App::new())))).await;
        // index.html shows "Loading…" until now: remove it, or say why nothing appeared.
        if let Some(loading) = document.get_element_by_id("loading_text") {
            match started {
                Ok(()) => loading.remove(),
                Err(e) => loading.set_text_content(Some(&format!("The app could not start in this browser: {e:?}"))),
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn side(skill: i32, flat: i32, sl: i32, adv: i32) -> Side {
        Side { skill, flat, sl, adv }
    }

    #[test]
    fn single_rolls_match_the_bot() {
        // Cases from ../test_rolls.py: (skill, flat, SL modifier, Advantage), roll -> (SL, success).
        for ((skill, flat, sl, adv), roll, want) in [
            ((72, 0, 0, 0), 26, (5, true)),
            ((54, 0, 0, 0), 94, (-4, false)),
            ((54, 0, 0, 0), 52, (0, true)),
            ((54, 0, 0, 0), 57, (0, false)),
            ((150, 0, 0, 0), 26, (13, true)),
            ((999, 0, 0, 0), 100, (89, true)),
            ((54, 20, 0, 0), 26, (5, true)),
            ((54, 0, 1, 0), 57, (1, true)),
            ((54, 0, -1, 0), 52, (-1, false)),
            ((54, 0, 2, 0), 74, (0, true)),
            ((54, 0, 0, 1), 62, (3, true)),     // swapped to 26
            ((54, 0, 0, 1), 26, (3, true)),     // never swapped to worse
            ((54, 0, 0, -1), 26, (-1, false)),  // must swap to 62
            ((54, 0, 0, 3), 62, (5, true)),     // 26 against 74
            ((54, 0, 0, -3), 26, (-3, false)),  // 62 against 34
            ((54, 0, 0, 1), 10, (5, true)),     // 10 swaps to 01...
            ((54, 0, 0, -1), 1, (4, true)),     // ...and 01 to 10
            ((54, 0, 0, -1), 100, (-5, false)), // 100 stays 100
        ] {
            let r = side(skill, flat, sl, adv).resolve(roll);
            assert_eq!((r.sl, r.success), want, "{skill} {flat} {sl} {adv} rolled {roll}");
        }
    }

    #[test]
    fn doubles_match_the_bot() {
        // Cases from ../test_rolls.py: (skill, SL modifier), roll -> (double, success).
        for ((skill, sl), roll, want) in [
            ((54, 0), 44, (true, true)),   // Critical
            ((54, 0), 55, (true, false)),  // Fumble
            ((54, 0), 100, (true, false)), // 00 + 0 is a double too
            ((150, 0), 100, (true, true)),
            ((54, 0), 45, (false, true)),
            ((54, 0), 10, (false, true)),
            ((54, 1), 55, (true, true)), // adjusted into a success, so a Critical
        ] {
            let r = side(skill, 0, sl, 0).resolve(roll);
            assert_eq!((r.double, r.success), want, "{skill} {sl} rolled {roll}");
        }
    }

    #[test]
    fn opposed_verdicts_match_the_bot() {
        let s = side(54, 0, 0, 0);
        assert_eq!(versus(s.resolve(61), s.resolve(83)), key(true, 2)); // -1 SL beats -3 SL by 2
        assert_eq!(versus(s.resolve(52), s.resolve(57)), key(true, 0)); // +0 beats -0
        assert_eq!(versus(s.resolve(52), s.resolve(52)), 0);
        assert_eq!(versus(side(54, 0, -1, 0).resolve(57), side(54, 30, 1, 0).resolve(26)), key(false, 8)); // -1 vs +7
    }

    #[test]
    fn chances_are_exact() {
        let mut i = Inputs { opposed: false, you: side(50, 0, 0, 0), ..Inputs::default() };
        assert_eq!(split(&outcomes(&i)).map(|p| (100.0 * p).round()), [50.0, 0.0, 50.0]);
        let t = total(&outcomes(&i));
        assert_eq!([t.crit[0], t.fumble[0]].map(|p| (100.0 * p).round()), [4.0, 6.0]); // 11-44, then 55-99 and 100
        i.you.adv = 1;
        let adv = split(&outcomes(&i))[0];
        i.you.adv = -1;
        let dis = split(&outcomes(&i))[0];
        assert!(dis < 0.5 && 0.5 < adv);
        // A mirror match is even, and every outcome adds up to 100%.
        i.opposed = true;
        i.opp = i.you;
        let [win, tie, lose] = split(&outcomes(&i));
        assert!((win - lose).abs() < 1e-9 && (win + tie + lose - 1.0).abs() < 1e-9);
        let t = total(&outcomes(&i));
        assert!((t.crit[0] - t.crit[1]).abs() < 1e-9 && (t.fumble[0] - t.fumble[1]).abs() < 1e-9);
    }

    #[test]
    fn default_table_matches_the_bot() {
        // Brute-forced through ../rolls.py for 45 against 55 with +2 SL and Advantage.
        let r = Results::new(Inputs::default());
        let t = total(&r.chances);
        assert_eq!([t.crit[0], t.fumble[0], t.crit[1], t.fumble[1]].map(|p| (100.0 * p).round()), [4.0, 6.0, 7.0, 3.0]);
        assert_eq!(r.table[0], ["Your net SL", "Chance", "This or better", "You crit", "You fumble", "Opponent crits", "Opponent fumbles"]);
        let row = |name: &str| r.table.iter().find(|row| row[0] == name).unwrap().clone();
        assert_eq!(row("+1 SL")[1..4], ["3.59%", "9.43%", "0.24%"]);
        assert_eq!(row("-3 SL")[4], "0.26%");
        assert_eq!(row("-4 SL")[5], "0.70%");
    }

    #[test]
    fn sweep_varies_the_chosen_side() {
        let r = Results::new(Inputs { vary: Some(Knob { opponent: true, field: Field::Sl }), ..Inputs::default() });
        assert_eq!(r.sweep[3].0, 2); // centred on the opponent's +2 SL
        assert!(r.sweep.windows(2).all(|w| w[0].1[2] < w[1].1[2])); // more SL for them, more wins for them
    }
}
