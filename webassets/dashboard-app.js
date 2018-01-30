var myApp = angular.module('dashboardApp', ['ngResource']);

myApp.filter("toArray", function () {
    return function (obj) {
        var result = [];
        angular.forEach(obj, function (val, key) {
            result.push({ "team": key, "score": val });
        });
        return result;
    };
});

myApp.controller('scoreboardController', ['$scope', '$rootScope', '$resource', '$timeout', function ($scope, $rootScope, $resource, $timeout) {

    $scope.init = function () {
        // The scores, on initialization, are an empty list.
        $scope.scores = {};
        $scope.scoresBack = {};
        $scope.team_names = {};
        $scope.ScoresResource = $resource(API_ENDPOINT + "/score/:team");
    };

    $scope.PopulateScores = function () {
        for (i in TEAMS) {
            t = TEAMS[i];
            team_id = null;
            if (typeof (t) == "object") {
                team_id = t.team_id;
                team_name = t.team_name;
                $scope.team_names[team_id] = team_name;
            }
            else {
                team_id = t;
                team_name = t.toString();
                $scope.team_names[team_id] = team_name;
            }
            // For each team, retrieve the score for that team.
            $scope.ScoresResource.get({
                team: team_id.toString()
            }, function (score) {
                $scope.scoresBack[$scope.team_names[score.team]] = score.score;
            });
        }
        return true;
    }

    $scope.ScoresRefresh = function () {
        var poll = function () {
            $timeout(function () {
                if ($scope.PopulateScores()) {
                    poll();
                }
            }, 30000);
        };
        poll();
    };

    $scope.ScoresRefreshOnce = function () {
        $scope.PopulateScores();

    };

    $scope.ScorePresent = function () {
        $scope.scores = Object.keys($scope.scoresBack).map(function (key) {
            return { "team": key, "score": $scope.scoresBack[key] };
        }).sort(function (a, b) {
            return b.team < a.team;
        });
        $timeout(function () {
            $scope.ScorePresent();
        }, 30000);
    };

    $scope.init();
    $scope.ScoresRefreshOnce();

    // 5 seconds should be plenty for the initial scores to arrive, so wait that long and then
    // present them.
    $timeout(function () {
        $scope.ScorePresent();
    }, 5000);
}]);
