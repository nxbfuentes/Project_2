import os
from pathlib import Path
from etl_project.assets.opensky_flights import (
    extract_opensky_flights,
    transform,
    transform_flight_data,
    enrich_airport_data,
    load,
)
from etl_project.connectors.opensky_flights import OpenSkyApiClient
import pytest
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import Table, MetaData, Column, String, Integer
from etl_project.connectors.postgresql import PostgreSqlClient
from datetime import datetime, timezone


@pytest.fixture
def setup_extract():
    load_dotenv()


def test_extract_opensky_flights(setup_extract):
    API_USERNAME = os.environ.get("API_USERNAME")
    API_PASSWORD = os.environ.get("API_PASSWORD")
    opensky_client = OpenSkyApiClient(username=API_USERNAME, password=API_PASSWORD)
    start_time = int(datetime(2023, 2, 6, tzinfo=timezone.utc).timestamp())
    end_time = int(datetime(2023, 2, 8, tzinfo=timezone.utc).timestamp())
    df = extract_opensky_flights(opensky_client, start_time, end_time)
    assert not df.empty


@pytest.fixture
def setup_input_flights_df():
    return pd.DataFrame(
        [
            {
                "icao24": "abc123",
                "firstSeen": 1609459200,
                "lastSeen": 1609462800,
                "estDepartureAirportHorizDistance": 100,
                "estDepartureAirportVertDistance": 50,
                "estArrivalAirportHorizDistance": 200,
                "estArrivalAirportVertDistance": 100,
            },
            {
                "icao24": "def456",
                "firstSeen": 1609459200,
                "lastSeen": 1609462800,
                "estDepartureAirportHorizDistance": 150,
                "estDepartureAirportVertDistance": 75,
                "estArrivalAirportHorizDistance": 250,
                "estArrivalAirportVertDistance": 125,
            },
        ]
    )


def test_transform(setup_input_flights_df):
    df = setup_input_flights_df
    transformed_df = transform(df)
    assert "estDepartureAirportDistance" in transformed_df.columns
    assert "estArrivalAirportDistance" in transformed_df.columns


@pytest.fixture
def setup_transformed_flights_df():
    return pd.DataFrame(
        [
            {
                "icao24": "abc123",
                "firstSeen": datetime(2021, 1, 1, 0, 0, 0),
                "lastSeen": datetime(2021, 1, 1, 1, 0, 0),
                "estDepartureAirport": "JFK",
                "estArrivalAirport": "LAX",
                "callsign": "ABC123",
                "estDepartureAirportDistance": 111.8,
                "estArrivalAirportDistance": 223.6,
            },
            {
                "icao24": "def456",
                "firstSeen": datetime(2021, 1, 1, 0, 0, 0),
                "lastSeen": datetime(2021, 1, 1, 1, 0, 0),
                "estDepartureAirport": "SFO",
                "estArrivalAirport": "ORD",
                "callsign": "DEF456",
                "estDepartureAirportDistance": 167.7,
                "estArrivalAirportDistance": 279.2,
            },
        ]
    )


@pytest.fixture
def setup_airports_df():
    return pd.DataFrame(
        [
            {
                "ident": "JFK",
                "type": "large_airport",
                "name": "John F Kennedy Intl",
                "iso_country": "US",
                "coordinates": "-73.7781,40.6413",
            },
            {
                "ident": "LAX",
                "type": "large_airport",
                "name": "Los Angeles Intl",
                "iso_country": "US",
                "coordinates": "-118.4085,33.9416",
            },
            {
                "ident": "SFO",
                "type": "large_airport",
                "name": "San Francisco Intl",
                "iso_country": "US",
                "coordinates": "-122.375,37.6188",
            },
            {
                "ident": "ORD",
                "type": "large_airport",
                "name": "Chicago O'Hare Intl",
                "iso_country": "US",
                "coordinates": "-87.9048,41.9786",
            },
        ]
    )


def test_enrich_airport_data(setup_transformed_flights_df, setup_airports_df):
    df_flights = setup_transformed_flights_df
    df_airports = setup_airports_df
    enriched_df = enrich_airport_data(df_flights, df_airports)
    assert "departure_airport_name" in enriched_df.columns
    assert "arrival_airport_name" in enriched_df.columns


@pytest.fixture
def setup_postgresql_client():
    load_dotenv()
    SERVER_NAME = os.environ.get("SERVER_NAME")
    DATABASE_NAME = os.environ.get("DATABASE_NAME")
    DB_USERNAME = os.environ.get("DB_USERNAME")
    DB_PASSWORD = os.environ.get("DB_PASSWORD")
    PORT = os.environ.get("PORT")

    postgresql_client = PostgreSqlClient(
        server_name=SERVER_NAME,
        database_name=DATABASE_NAME,
        username=DB_USERNAME,
        password=DB_PASSWORD,
        port=PORT,
    )
    return postgresql_client


@pytest.fixture
def setup_transformed_table_metadata():
    table_name = "test_table"
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("icao24", String, primary_key=True),
        Column("firstSeen", String),
        Column("lastSeen", String),
        Column("estDepartureAirport", String),
        Column("estArrivalAirport", String),
        Column("callsign", String),
        Column("estDepartureAirportDistance", Integer),
        Column("estArrivalAirportDistance", Integer),
        Column("departure_airport_name", String),
        Column("arrival_airport_name", String),
    )
    return table_name, table, metadata


def test_load(
    setup_postgresql_client,
    setup_transformed_flights_df,
    setup_transformed_table_metadata,
):
    postgresql_client = setup_postgresql_client
    df = setup_transformed_flights_df
    table_name, table, metadata = setup_transformed_table_metadata
    postgresql_client.drop_table(table_name)  # reset
    load(
        df=df,
        postgresql_client=postgresql_client,
        table=table,
        metadata=metadata,
        load_method="upsert",
    )
    assert len(postgresql_client.select_all(table=table)) == 2

    load(
        df=df,
        postgresql_client=postgresql_client,
        table=table,
        metadata=metadata,
        load_method="upsert",
    )
    assert len(postgresql_client.select_all(table=table)) == 2
    postgresql_client.drop_table(table_name)  # reset
