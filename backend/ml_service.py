import os
import joblib
import pandas as pd


# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

MODEL_DIR = os.path.join(
    BASE_DIR,
    "models"
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data"
)


# ============================================================
# LOAD MODEL
# ============================================================

def load_model(filename):

    path = os.path.join(
        MODEL_DIR,
        filename
    )

    if not os.path.exists(path):

        raise FileNotFoundError(
            f"Model not found: {path}"
        )

    return joblib.load(path)


# ============================================================
# LOAD ALL MODELS
# ============================================================

crowd_regressor = load_model(
    "crowd_regressor.pkl"
)

crowd_classifier = load_model(
    "crowd_classifier.pkl"
)

wait_regressor = load_model(
    "wait_regressor.pkl"
)


# ============================================================
# LOAD DATASETS
# ============================================================

def load_datasets():

    crowd_file = os.path.join(
        DATA_DIR,
        "Dataset1_CrowdPrediction_FINAL.csv"
    )

    wait_file = os.path.join(
        DATA_DIR,
        "Dataset2_WaitingTime_FINAL.csv"
    )


    if not os.path.exists(crowd_file):

        raise FileNotFoundError(
            f"Crowd dataset not found: {crowd_file}"
        )


    if not os.path.exists(wait_file):

        raise FileNotFoundError(
            f"Waiting dataset not found: {wait_file}"
        )


    crowd_data = pd.read_csv(
        crowd_file
    )

    wait_data = pd.read_csv(
        wait_file
    )


    print("=" * 70)
    print("DATASETS LOADED")
    print("=" * 70)

    print(
        "Crowd dataset:",
        crowd_data.shape
    )

    print(
        "Waiting dataset:",
        wait_data.shape
    )

    print("=" * 70)


    return crowd_data, wait_data


# ============================================================
# GLOBAL DATASETS
# ============================================================

df_crowd, df_wait = load_datasets()


# ============================================================
# CROWD PREDICTION
# ============================================================
#
# USER PROVIDES:
#
# date
# day_of_week
# month
# is_weekend
# is_public_holiday
# festival_name
# festival_impact
# time_slot
# darshan_type
#
# SYSTEM PROVIDES:
#
# historical_daily_avg
#
# ============================================================

def predict_crowd(data):

    # --------------------------------------------------------
    # Get historical records
    # --------------------------------------------------------

    historical_rows = df_crowd[
        (df_crowd["day_of_week"] == data["day_of_week"])
        &
        (df_crowd["month"] == data["month"])
        &
        (df_crowd["darshan_type"] == data["darshan_type"])
    ]


    # --------------------------------------------------------
    # Historical daily average
    # --------------------------------------------------------

    if len(historical_rows) > 0:

        historical_daily_avg = float(
            historical_rows[
                "historical_daily_avg"
            ].mean()
        )

    else:

        historical_daily_avg = float(
            df_crowd[
                "historical_daily_avg"
            ].mean()
        )


    # --------------------------------------------------------
    # Create model input
    # --------------------------------------------------------

    features = pd.DataFrame([
        {

            "day_of_week":
                data["day_of_week"],

            "month":
                data["month"],

            "is_weekend":
                data["is_weekend"],

            "is_public_holiday":
                data["is_public_holiday"],

            "festival_name":
                data["festival_name"],

            "festival_impact":
                data["festival_impact"],

            "time_slot":
                data["time_slot"],

            "darshan_type":
                data["darshan_type"],

            "historical_daily_avg":
                historical_daily_avg

        }
    ])


    # --------------------------------------------------------
    # Crowd regression
    # --------------------------------------------------------

    crowd_prediction = (
        crowd_regressor.predict(
            features
        )[0]
    )


    # --------------------------------------------------------
    # Crowd classification
    # --------------------------------------------------------

    crowd_level = (
        crowd_classifier.predict(
            features
        )[0]
    )


    # --------------------------------------------------------
    # Return result
    # --------------------------------------------------------

    return {

        "expected_crowd_count":
            int(
                round(
                    crowd_prediction
                )
            ),

        "crowd_level":
            str(
                crowd_level
            )

    }


# ============================================================
# WAITING-TIME PREDICTION
# ============================================================
#
# ADMIN PROVIDES:
#
# date
# day_of_week
# month
# time_slot
# darshan_type
# current_queue_count
# waiting_compartments
# queue_occupancy_percent
# people_entering_per_hour
# people_processed_per_hour
# current_crowd_level
# is_weekend
# is_public_holiday
# festival_impact
# ssd_tokens_issued
# ssd_tokens_remaining
#
# SYSTEM PROVIDES:
#
# historical_avg_wait_minutes
#
# ============================================================

def predict_waiting_time(data):

    # --------------------------------------------------------
    # Find historical observations for this
    # darshan type and time slot
    # --------------------------------------------------------

    historical_rows = df_wait[
        (df_wait["darshan_type"] == data["darshan_type"])
        &
        (df_wait["time_slot"] == data["time_slot"])
    ]


    # --------------------------------------------------------
    # Historical average waiting time
    # --------------------------------------------------------

    if len(historical_rows) > 0:

        historical_avg_wait_minutes = float(
            historical_rows[
                "historical_avg_wait_minutes"
            ].median()
        )

    else:

        historical_avg_wait_minutes = float(
            df_wait[
                "historical_avg_wait_minutes"
            ].median()
        )


    # --------------------------------------------------------
    # Create model input
    # --------------------------------------------------------

    features = pd.DataFrame([
        {

            "day_of_week":
                data["day_of_week"],

            "month":
                data["month"],

            "time_slot":
                data["time_slot"],

            "darshan_type":
                data["darshan_type"],

            "current_queue_count":
                data["current_queue_count"],

            "waiting_compartments":
                data["waiting_compartments"],

            "queue_occupancy_percent":
                data["queue_occupancy_percent"],

            "people_entering_per_hour":
                data["people_entering_per_hour"],

            "people_processed_per_hour":
                data["people_processed_per_hour"],

            "current_crowd_level":
                data["current_crowd_level"],

            "is_weekend":
                data["is_weekend"],

            "is_public_holiday":
                data["is_public_holiday"],

            "festival_impact":
                data["festival_impact"],

            "ssd_tokens_issued":
                data["ssd_tokens_issued"],

            "ssd_tokens_remaining":
                data["ssd_tokens_remaining"],

            "historical_avg_wait_minutes":
                historical_avg_wait_minutes

        }
    ])


    # --------------------------------------------------------
    # Predict
    # --------------------------------------------------------

    waiting_prediction = (
        wait_regressor.predict(
            features
        )[0]
    )


    waiting_prediction = max(
        0,
        waiting_prediction
    )


    waiting_minutes = int(
        round(
            waiting_prediction
        )
    )


    waiting_hours = round(
        waiting_minutes / 60,
        2
    )


    # --------------------------------------------------------
    # Return result
    # --------------------------------------------------------

    return {

        "waiting_time_minutes":
            waiting_minutes,

        "waiting_time_hours":
            waiting_hours

    }