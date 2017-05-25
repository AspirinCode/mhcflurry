import numpy
import pandas
numpy.random.seed(0)

from mhcflurry import Class1NeuralNetwork, Class1AffinityPredictor

from nose.tools import eq_, assert_raises
from numpy import testing

from mhcflurry.downloads import get_path

allele = "HLA-A*02:05"

df = pandas.read_csv(
        get_path(
            "data_curated", "curated_training_data.csv.bz2"))
df = df.ix[df.allele == allele]
df = df.ix[
    df.peptide.str.len() == 9
]
df = df.ix[
    df.measurement_type == "quantitative"
]
df = df.ix[
    df.measurement_source == "kim2014"
]

# Memorize the dataset.
hyperparameters = dict(
    activation="tanh",
    layer_sizes=[64],
    max_epochs=500,
    early_stopping=False,
    validation_split=0.0,
    locally_connected_layers=[],
    dense_layer_l1_regularization=0.0,
    dropout_probability=0.0)


def test_class1_neural_network_a0205_training_accuracy():
    predictor = Class1NeuralNetwork(**hyperparameters)
    predictor.fit(df.peptide.values, df.measurement_value.values)
    ic50_pred = predictor.predict(df.peptide.values)
    ic50_true = df.measurement_value.values
    eq_(len(ic50_pred), len(ic50_true))
    testing.assert_allclose(
        numpy.log(ic50_pred),
        numpy.log(ic50_true),
        rtol=0.2,
        atol=0.2)


def test_class1_affinity_predictor_a0205_training_accuracy():
    predictor = Class1AffinityPredictor()
    predictor.fit_allele_specific_predictors(
        n_models=2,
        architecture_hyperparameters=hyperparameters,
        allele=allele,
        peptides=df.peptide.values,
        affinities=df.measurement_value.values,
    )
    ic50_pred = predictor.predict(df.peptide.values, allele=allele)
    ic50_true = df.measurement_value.values
    eq_(len(ic50_pred), len(ic50_true))
    testing.assert_allclose(
        numpy.log(ic50_pred),
        numpy.log(ic50_true),
        rtol=0.2,
        atol=0.2)

    ic50_pred_df = predictor.predict_to_dataframe(
        df.peptide.values, allele=allele)
    print(ic50_pred_df)

    ic50_pred_df2 = predictor.predict_to_dataframe(
        df.peptide.values,
        allele=allele,
        include_individual_model_predictions=True)
    print(ic50_pred_df2)

    # Test an unknown allele
    eq_(predictor.supported_alleles, [allele])
    ic50_pred = predictor.predict(
        df.peptide.values,
        allele="HLA-A*02:01",
        throw=False)
    assert numpy.isnan(ic50_pred).all()

    assert_raises(
        ValueError,
        predictor.predict,
        df.peptide.values,
        allele="HLA-A*02:01")


    eq_(predictor.supported_alleles, [allele])
    assert_raises(
        ValueError,
        predictor.predict,
        ["AAAAA"],  # too short
        allele=allele)
    assert_raises(
        ValueError,
        predictor.predict,
        ["AAAAAAAAAAAAAAAAAAAA"],  # too long
        allele=allele)
    ic50_pred = predictor.predict(
        ["AAAAA", "AAAAAAAAA", "AAAAAAAAAAAAAAAAAAAA"],
        allele=allele,
        throw=False)
    assert numpy.isnan(ic50_pred[0])
    assert not numpy.isnan(ic50_pred[1])
    assert numpy.isnan(ic50_pred[2])

