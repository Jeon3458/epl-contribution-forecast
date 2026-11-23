# EPL Contribution Forecast

Do player-level contribution metrics improve Premier League match outcome prediction beyond team-level baselines?

This project builds on an undergraduate team study I worked on in 2025. The core idea stays the same: predict match outcomes from the players in each lineup, not only from team-level statistics. What changes is the experiment. Looking back at the original work with what I have learned since, I found several limitations in how it was evaluated. This version keeps the original player contribution metrics (AC, DC, MI) and rebuilds the evaluation so the results can be trusted.

> **Status:** In progress. Results below will be filled in as each stage is completed.

---

## Building on the Original Study

### Version 1 (2025)

The original study ([EPL-Match-Predictor-ML](https://github.com/Jeon3458/EPL-Match-Predictor-ML)) was a team project at Hanseo University. I implemented the data pipeline and the models. It introduced position-specific contribution metrics and combined them with recent form, head-to-head records, and goal statistics. A Random Forest model reached 57.4% accuracy on its test set.

The main idea was worth keeping. Building team strength from individual players makes it possible to reflect lineup changes, injuries, and rotation, which team averages cannot capture.

### Limitations at the time

At that stage, the focus was on building features and comparing models. Evaluation design received much less attention. Reviewing the code later showed four limitations.

1. **Data leakage.** Player contributions were computed from full-season statistics. This included the win rate of the same matches the model was predicting.
2. **Small test set.** The random 80/20 split left only 54 test matches. With so few matches, the confidence interval for accuracy was very wide.
3. **No baseline.** Predicting "home win" for every match already gave 50% on the same test set. Without this comparison, 57.4% looked more meaningful than it was.
4. **Random split.** Matches from later dates were mixed into the training data. This does not reflect how predictions are made in practice.

### What changes in Version 2

| Area | Version 1 | Version 2 |
|---|---|---|
| Contribution metrics | AC, DC, MI with hand-set weights | Same metrics kept, plus a comparison with learned weights |
| Feature timing | Full-season statistics | Previous-season statistics and past matches only |
| Data source | FootyStats CSV exports and separate lineup files | FootyStats API: results, lineups, and player stats linked by player ID |
| Data size | About 270 matches | 5 seasons (2021/22 to 2025/26), 1,900 matches |
| Train/test split | Random 80/20 | Time-based, test on the latest season (2025/26) |
| Baselines | None | Always home win, pre-match PPG, recent form |
| Metrics | Accuracy only | Accuracy, macro F1, log loss, RPS |
| Main question | How accurate is the model? | Do contribution features add value over baselines? |
| Code | Single Colab notebook | Python scripts, reproducible runs |
| Deployment | None | Planned AWS pipeline |

The accuracy in Version 2 may be lower than 57.4%. That would not mean the project went backward. It would mean the new number is closer to what the model can actually do.

## Research Question

Do AC, DC, and MI features add predictive value when compared with simple team-level baselines under a time-based evaluation?

A negative answer is also a valid result. The goal is a reliable evaluation, not a high accuracy number.

## Player Contribution Metrics

The metric design comes from the original study (framework by Jiheon Kim).

| Position | Metric | Formula (per 90 minutes) |
|---|---|---|
| Forward | Attack (AC) | 0.45 Goals + 0.25 xG + 0.15 Assists + 0.05 Shots + 0.10 Finishing efficiency |
| Midfielder | Attack (AC) | 0.3 Goals + 0.3 Assists + 0.4 Key passes |
| Midfielder | Defense (DC) | 0.6 Tackles + 0.4 Interceptions |
| Defender | Defense (DC) | 0.3 Tackles + 0.3 Interceptions + 0.25 Clearances + 0.15 Aerial duels won |
| Goalkeeper | Defense (DC) | 0.4 Saves + 0.4 Clean sheets - 0.2 Goals conceded |
| All | Match Impact (MI) | Team win rate when the player started |
| Total | Contribution | 0.4 AC + 0.4 DC + 0.2 MI, scaled to 0-100 |

## Method

### Leakage control
- Player AC and DC use **previous-season** statistics only.
- MI uses **only matches played before** the match being predicted.
- Players with no previous-season data receive a documented default value. Promoted teams are handled the same way.

### Evaluation design
- **Data:** 2021/22 to 2025/26 seasons (1,900 matches).
- **2020/21 is used only as history**, for previous-season statistics and past matches. It was played without fans, and it is the only season in the data where away wins (40.3%) outnumbered home wins (37.9%).
- **Split:** Train on earlier seasons and test on the most recent season (2025/26). A rolling season-by-season evaluation is also reported.
- **Metrics:** Accuracy, macro F1, log loss, and Ranked Probability Score (RPS).

### Baselines
| Baseline | Description |
|---|---|
| Always home win | Predicts a home win for every match |
| Pre-match PPG | Uses points per game before the match |
| Recent form | Average points from the last 5 matches |

### Experiments
1. **Ablation:** baseline features only, baseline + contribution features, contribution features only.
2. **Models:** Multinomial logistic regression, Random Forest, Gradient Boosting.
3. **Weights:** hand-set metric weights compared with weights learned from data.

## Results

| Feature set | Model | Accuracy | Macro F1 | Log loss | RPS |
|---|---|---|---|---|---|
| Always home win | - | TBD | TBD | - | - |
| Baseline only | TBD | TBD | TBD | TBD | TBD |
| Baseline + contribution | TBD | TBD | TBD | TBD | TBD |
| Contribution only | TBD | TBD | TBD | TBD | TBD |

### Version 1 vs Version 2

| | Version 1 | Version 2 |
|---|---|---|
| Test set | 54 matches, random split | 380 matches, 2025/26 season |
| Best accuracy | 0.574 (Random Forest) | TBD |
| Always home win | 0.500 | TBD |
| Gain over baseline | +0.074 | TBD |

## Data

Match results, lineups, and player statistics come from the [FootyStats API](https://footystats.org/api). Lineups and player statistics share the same player IDs, so no name matching is needed. **Raw and processed data are not included in this repository**, because FootyStats does not allow redistribution. To reproduce the results, you need your own API key. See `data/README.md` for the steps and for known data issues.

## Project Structure

```
epl-contribution-forecast/
├── data/
│   ├── README.md          # how to get the data, known data issues
│   ├── raw/               # API responses (not included)
│   └── processed/         # clean tables (not included)
├── src/
│   ├── collect.py         # download raw data from the FootyStats API
│   ├── load.py            # build clean tables from the raw data
│   ├── contribution.py    # AC, DC, MI calculation (planned)
│   ├── features.py        # pre-match feature building (planned)
│   ├── baselines.py       # (planned)
│   ├── train.py           # (planned)
│   └── evaluate.py        # (planned)
├── notebooks/             # exploration only
├── results/
├── requirements.txt
└── README.md
```

## How to Run

```bash
pip install -r requirements.txt
python3 -m src.collect     # download raw data (needs an API key in .env)
python3 -m src.load        # build clean tables in data/processed/
```

Training and evaluation commands will be added as those stages are completed.

## Roadmap

- [x] Rebuild the data pipeline (FootyStats API: results, lineups, player stats)
- [ ] Leakage-free contribution features
- [ ] Baselines and ablation experiments
- [ ] Learned vs hand-set weights
- [ ] AWS pipeline: S3 storage, scheduled data ingestion, training job, prediction API

## Credits

Original study: Jiheon Kim (research framework and contribution metrics), Hyunseong Jeon (implementation), HyeonGue Kim, Youngju Im, Euichan Jeong (data collection), with Prof. JunBum Park (advisor), Hanseo University.

This redesign and re-evaluation: Hyunseong Jeon.

## License

MIT