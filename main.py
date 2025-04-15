import re
import yaml
import json
import os
import logging
import time
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import NoBrokersAvailable
from dotenv import load_dotenv

class LogParser:
    def __init__(self, config_path):
        load_dotenv()
        self.setup_logging()
        self.config = self.load_config(config_path)

        self.successful_logs = 0  
        self.failed_logs = 0

        self.kafka_broker = os.getenv("KAFKA_BROKER")
        self.topic_in = os.getenv("LFR_TOPIC")
        self.topic_out = os.getenv("EPT_TOPIC")
        self.encoding = os.getenv("ENCODING", "utf-8")

        self.consumer = None
        self.producer = None
        self.connect_to_kafka()

    def setup_logging(self):
        current_file = os.path.basename(__file__)
        logging.basicConfig(
            filename="log_parser.log",
            filemode="a",
            format=f"%(asctime)s - %(levelname)s - {current_file} - %(message)s",
            level=logging.DEBUG
        )
        logging.info("Initialized LogParser")

    def load_config(self, config_path):
        try:
            with open(config_path, 'r') as file:
                logging.info(f"Loading configuration from {config_path}")
                return yaml.safe_load(file)
        except Exception as e:
            logging.error(f"Failed to load configuration: {e}")
            raise

    def connect_to_kafka(self):
        print("Connecting to Kafka...", flush=True)
        while True:
            try:
                self.consumer = KafkaConsumer(
                    self.topic_in,
                    bootstrap_servers=self.kafka_broker,
                    auto_offset_reset="earliest",
                    group_id="ept-group"
                )
                self.producer = KafkaProducer(bootstrap_servers=self.kafka_broker)
                print(f"Connected to Kafka! Listening on {self.topic_in}", flush=True)
                break
            except NoBrokersAvailable:
                print("Kafka not available yet, retrying in 5 seconds...", flush=True)
                time.sleep(5)

    def strip_ansi_codes(self, text):
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def parse_log_entry(self, log):
        log = self.strip_ansi_codes(log)
        regex = re.compile(self.config['log_pattern']['regex'], re.VERBOSE)
        match = regex.match(log)
        if match:
            return match.groupdict()
        return None

    def process_log(self, full_log):
        log_text = " ".join(full_log)
        parsed_entry = self.parse_log_entry(log_text)
        log_file_path = self.config['file_paths']['log_file']
        base_filename = os.path.splitext(os.path.basename(log_file_path))[0]

        if parsed_entry:
            parsed_entry['log_file'] = base_filename
            payload = json.dumps(parsed_entry).encode(self.encoding)
            self.producer.send(self.topic_out, payload)
            print(f"Sent to {self.topic_out}: {parsed_entry}", flush=True)
            self.successful_logs += 1
        else:
            logging.warning(f"Failed to parse log entry: {log_text}")
            self.failed_logs += 1

    def parse_log_stream(self):
        full_log = []

        for msg in self.consumer:
            log_message = msg.value.decode(self.encoding)
            lines = log_message.splitlines()

            for line in lines:
                line = self.strip_ansi_codes(line)
                if line.startswith("[v "):
                    if full_log:
                        self.process_log(full_log)
                    full_log = [line.strip()]
                else:
                    full_log.append(line)

            if full_log:
                self.process_log(full_log)

        logging.info("Log parsing completed.")
        logging.info(f"Successful logs: {self.successful_logs}")
        logging.info(f"Failed logs: {self.failed_logs}")

if __name__ == "__main__":
    parser = LogParser("config.yaml")
    parser.parse_log_stream()
