import numpy as np
import pandas as pd
import sys, os, json

from preprocess import preprocess_text
from evaluate import evaluate_models
from make_features import get_transformer_list, validate_arguments


if __name__ == '__main__':

    if len(sys.argv) != 2:
        print("Usage: python baselines.py params.json")
        exit(1)

    # load parameters from (generated) json file. See 'gen_params.py' 
    with open(sys.argv[1], 'r') as fo:
        params = json.load(fo)

    for par in params.keys():
        locals()[par] = params[par]

    # Reading the dataset
    df = pd.read_pickle(data_dir + '/' + dataframe_name)

    print("Dataframe has {} rows and {} columns".format(df.shape[0], df.shape[1]))

    validate_arguments(df, text_col, feature_cols, feature_methods)
    #Preprocessing the data
    print("Preprocessing", preprocessing)
    df = preprocess_text(df, text_col, preprocessing ,data_dir)
    # Transform features
    X, lookup_dict = get_transformer_list(df, data_dir, text_col, feature_methods, feature_cols,
                                            ordinal_cols, categorical_cols, ngrams=ngrams, bom_method=embedding_method,
                                            training_corpus=training_corpus, dictionary=dictionary,
                                            comp_measure='cosine-sim', random_seed=random_seed, feature_reduce=feature_reduce)

    for i in range(len(lookup_dict)):
        new_col = np.array([row[i] for row in X])
        col_name = lookup_dict[i]
        df.loc[:, col_name] = pd.Series(new_col, index=df.index)
    
    df.to_pickle("liwc_features.pkl")
    feature_dest = "saved_features.csv"
    #save_features(X, lookup_dict, feature_dest)
    # Performing classification
    evaluate_models(df, X, targets, lookup_dict, models, random_seed, feature_methods, scoring_dir, config_text, metrics, output_name)

