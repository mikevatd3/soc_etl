import click
import pandas as pd
import pandera as pa
from pandera.typing import Series
from pandera.errors import SchemaError
import tomli

from soc import setup_logging, db_engine, metadata_engine
from metadata_audit.capture import record_metadata
from sqlalchemy.orm import sessionmaker

logger = setup_logging()

TABLE_NAME = "definitions"

with open("metadata.toml", "rb") as md:
    metadata = tomli.load(md)


class SOCDefinitions(pa.DataFrameModel):
    """
    This is one of two tables that make sense to include
    """

    code: str = pa.Field(unique=True)
    group: str = pa.Field()
    title: str = pa.Field()
    definition: str = pa.Field(nullable=True)

    class Config:  # type: ignore
        strict = True
        coerce = True

    @pa.check("definition")
    def count_descriptions(cls, definition: Series[str]) -> bool:
        """
        It's okay for some of these to be null, but if there are too many
        it could indicate a problem.
        """
        return (~definition.isna()).sum() == 867


@click.command()
@click.argument("edition_date")
def main(edition_date):
    edition = metadata["tables"][TABLE_NAME]["editions"][edition_date]

    result = (
        pd.read_csv(edition["raw_path"])
        .rename(
            columns={
                'SOC Code': 'code',
                'SOC Group': 'group',
                'SOC Title': 'title',
                'SOC Definition': 'description',
            }
        )
    )

    logger.info(f"Cleaning {TABLE_NAME} was successful validating schema.")

    # Validate
    try:
        validated = SOCDefinitions.validate(result)
        logger.info(
            f"Validating {TABLE_NAME} was successful. Recording metadata."
        )
    except SchemaError as e:
        logger.error(f"Validating {TABLE_NAME} failed.", e)

    with metadata_engine.connect() as db:
        logger.info("Connected to metadata schema.")

        record_metadata(
            SOCDefinitions,
            __file__,
            TABLE_NAME,
            metadata,
            edition_date,
            result,
            sessionmaker(bind=db)(),
            logger,
        )

        db.commit()
        logger.info("successfully recorded metadata")

    with db_engine.connect() as db:
        logger.info("Metadata recorded, pushing data to db.")

        validated.to_sql(  # type: ignore
            TABLE_NAME, db, index=False, schema="soc", if_exists="replace"
        )


if __name__ == "__main__":
    main()
