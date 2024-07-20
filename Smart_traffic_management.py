import torch
import cv2
import numpy as np
import os
from ultralytics import YOLO
import logging
import RPi.GPIO as GPIO
import time
from telegram import Bot

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Telegram bot token and chat ID
TELEGRAM_BOT_TOKEN = '# Replace with your telegram bot token'
TELEGRAM_CHAT_ID = ' # Replace with your chat ID' 
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Load YOLOv8n accident detection model
accident_model = YOLO('yolov8n_accident_detection.pt')

# Specify the image paths for the four lanes
image_paths = [
    r"Images/IMG_3/IMG_3.jpg",
    r"Images/IMG_4/IMG_4.jpg",
    r"Images/IMG_5/IMG_5.jpeg",
    r"Images/IMG_9/IMG_9.jpg"
]

# Directory to save detected vehicle images
output_dir = r"Detected_Vehicles"
os.makedirs(output_dir, exist_ok=True)

# Initialize a dictionary to hold vehicle counts for each lane
vehicle_counts = {}
accident_detected = False

# Loop through each image path
for i, image_path in enumerate(image_paths):
    # Check if the image file exists
    if not os.path.exists(image_path):
        logging.error(f"Image not found: {image_path}")
        continue

    # Load the image
    image = cv2.imread(image_path)

    # Check if the image was successfully loaded
    if image is None:
        logging.error(f"Failed to load image: {image_path}")
        continue

    # Perform detection
    results = accident_model(image)

    # Initialize vehicle count for this image
    vehicle_count = 0

    # Define vehicle class IDs (COCO dataset: 2=car, 3=motorcycle, 5=bus, 7=truck)
    vehicle_class_ids = [2, 3, 5, 7]

    # Check for accidents
    for result in results:
        boxes = result.boxes
        for box in boxes:
            class_id = int(box.cls)
            confidence = float(box.conf)

            if confidence > 0.5:
                if class_id == 0:  # Accident class ID
                    accident_detected = True
                    accident_lane = i + 1
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.putText(image, "Accident", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

                if class_id in vehicle_class_ids:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(image, "Vehicle", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    vehicle_count += 1

    # Store vehicle count for this lane
    vehicle_counts[f"lane_{i+1}"] = vehicle_count

    # Save the image with detections
    output_image_path = os.path.join(output_dir, f"detected_vehicles_lane_{i+1}.jpg")
    cv2.imwrite(output_image_path, image)
    logging.info(f"Output image saved to {output_image_path}")

# Save vehicle counts to file
vehicle_count_file = os.path.join(output_dir, "vehicle_counts.txt")
with open(vehicle_count_file, "w") as f:
    for lane, count in vehicle_counts.items():
        f.write(f"{lane}: {count}\n")
logging.info(f"Vehicle counts saved to {vehicle_count_file}")

# Function to adjust green signal time based on vehicle counts
def adjust_green_signal_time(vehicle_counts):
    base_green_time = 10  # Base green time in seconds
    vehicle_multiplier = 2  # Green time increases by 2 seconds per vehicle

    green_times = {}
    for lane, count in vehicle_counts.items():
        green_times[lane] = base_green_time + (count * vehicle_multiplier)
    return green_times

# Adjust green signal time based on vehicle counts
green_times = adjust_green_signal_time(vehicle_counts)

# Save green times to file
green_time_file = os.path.join(output_dir, "green_times.txt")
with open(green_time_file, "w") as f:
    for lane, timet in green_times.items():
        f.write(f"{lane}: {timet}\n")
logging.info(f"Green times saved to {green_time_file}")

# Define GPIO pins for each lane
LANE_PINS = {
    "lane_1": {"red": 11, "yellow": 9, "green": 10},
    "lane_2": {"red": 18, "yellow": 23, "green": 24},
    "lane_3": {"red": 16, "yellow": 20, "green": 21},
    "lane_4": {"red": 26, "yellow": 19, "green": 13}
}

# Function to set up GPIO
def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    for lane_pins in LANE_PINS.values():
        GPIO.setup(lane_pins["red"], GPIO.OUT)
        GPIO.setup(lane_pins["yellow"], GPIO.OUT)
        GPIO.setup(lane_pins["green"], GPIO.OUT)

# Function to control the traffic light for a lane
def control_traffic_light(lane, green_time):
    red_pin = LANE_PINS[lane]["red"]
    yellow_pin = LANE_PINS[lane]["yellow"]
    green_pin = LANE_PINS[lane]["green"]

    # Red light on for all lanes except the current one
    for l in LANE_PINS:
        if l != lane:
            GPIO.output(LANE_PINS[l]["red"], GPIO.HIGH)
            GPIO.output(LANE_PINS[l]["yellow"], GPIO.LOW)
            GPIO.output(LANE_PINS[l]["green"], GPIO.LOW)

    # Red light on for the current lane
    GPIO.output(red_pin, GPIO.HIGH)
    GPIO.output(yellow_pin, GPIO.LOW)
    GPIO.output(green_pin, GPIO.LOW)
    time.sleep(4)  # Fixed red time

    # Yellow light on
    GPIO.output(red_pin, GPIO.LOW)
    GPIO.output(yellow_pin, GPIO.HIGH)
    GPIO.output(green_pin, GPIO.LOW)
    time.sleep(5)  # Fixed yellow time (last 5 seconds)

    # Green light on
    GPIO.output(red_pin, GPIO.LOW)
    GPIO.output(yellow_pin, GPIO.LOW)
    GPIO.output(green_pin, GPIO.HIGH)
    time.sleep(green_time)  # Dynamic green time

# Function to control the traffic lights sequentially
def run_traffic_lights():
    try:
        while True:
            for lane in LANE_PINS:
                if accident_detected and lane == f"lane_{accident_lane}":
                    logging.info(f"Lane {lane} skipped due to accident.")
                    continue
                
                green_time = green_times[lane]
                control_traffic_light(lane, green_time)
                send_telegram_alert()  # Send Telegram alert if accident detected

                # Ensure immediate switch to green for the next lane after yellow
                if lane != "lane_4":
                    next_lane = f"lane_{int(lane.split('_')[1]) + 1}"
                    next_green_time = green_times[next_lane]
                    control_traffic_light(next_lane, next_green_time)

    except KeyboardInterrupt:
        logging.info("Traffic light control interrupted by user.")
    finally:
        GPIO.cleanup()

# Read green signal times from the file
def read_green_times(file_path):
    green_times = {}
    try:
        with open(file_path, "r") as file:
            for line in file:
                lane, timet = line.strip().split(":")
                green_times[lane.strip()] = int(timet.strip())
    except FileNotFoundError:
        logging.error(f"Error: The file {file_path} was not found.")
    except ValueError:
        logging.error("Error: The green time in the file is not a valid integer.")
    return green_times

# Function to send Telegram alert
def send_telegram_alert():
    try:
        if accident_detected:
            message = "An accident has been detected in one of the lanes. Please take necessary action."
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
            logging.info("Telegram alert sent successfully.")
    except Exception as e:
        logging.error(f"Failed to send Telegram alert: {e}")

def main():
    setup_gpio()

    # Read green times for each lane
    green_times = read_green_times(os.path.join(output_dir, "green_times.txt"))

    try:
        run_traffic_lights()
    except Exception as e:
        logging.error(f"Error in main loop: {e}")
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()
