<?php
// return an array holdng subdirectory names of the provided directory.
// element 0 is the "baseline" directory name
// element 1 is the "previous" directory name
function get_subdirs($top_dir)
{
  if ( ! is_dir($top_dir)) {
    return array("", "");
  }

  $graphdirs = array_diff(scandir($top_dir), array(".", ".."));
  $previous = "";
  $baseline = "";
  for ($sdi=0; $sdi < count($graphdirs); $sdi++) {
    $entry = $graphdirs[$sdi+2];
    if ( (preg_match('/202[0-9]/', $entry) ) || (preg_match('/previous/', $entry))) {
      $previous = $entry;
    }
    else {
      $baseline = $entry;
    }
  }
  $return_array = array($baseline, $previous);
  return $return_array;
}

function build_date_table()
{
  // set the path to the images
  $web_path = "/projects/mpas-jedi/weekly-cycling/cylc_graphs";
  $img_path = "/net/htdocs$web_path";

  // grab the directories
  $img_dirs = array_diff(scandir($img_path,1),array(".",".."));

  // loop thru the directories
  for ($a=0; $a < count($img_dirs); $a++) {
    // set the dir
    $dir = $img_dirs[$a];

    // only use valid dirs
    if ( (preg_match('/202[0-9]/', $dir) ) &&
         (is_dir("$img_path/$dir")) ) {
      $subdirs = array_diff(scandir("$img_path/$dir"), array(".", ".."));
      if (substr_compare($subdirs[2], ".failed", -7) == 0) {
        $base_model_anchor = "<a href=$web_path/$dir/$subdirs[2]> Failed</a>";
        $base_obs_anchor = $base_model_anchor;
        $prev_model_anchor = $base_model_anchor;
        $prev_obs_anchor = $base_model_anchor;
        $color="red";
      }
      else {
        $model_dirs = get_subdirs("$img_path/$dir/$subdirs[2]/model");

        $obs_dirs = get_subdirs("$img_path/$dir/$subdirs[2]/obs");

        $base_title = $model_dirs[0];
        $prev_title = $model_dirs[1];
        $model_hdrs = "Date,Graph%20Type";
        $base_model_dir = "$web_path/$dir/$subdirs[2]/model/$model_dirs[0]/mpas_analyses";
        $base_model_anchor = "
            <a href=web/listgraphs.php/?baseline=$base_title&tbl_hdrs=$model_hdrs&date=$dir&column1=$dir&path=$base_model_dir&suffix=mmgfsan>View Model Plots</a>";
        $prev_model_dir = "$web_path/$dir/$subdirs[2]/model/$model_dirs[1]/mpas_analyses";
        $prev_model_anchor = "
            <a href=web/listgraphs.php/?baseline=$prev_title&tbl_hdrs=$model_hdrs&date=$dir&column1=$dir&path=$prev_model_dir&suffix=mmgfsan>View Model Plots</a>";
        $obs_hdrs = "Date,Analysis%20Type";
        $base_obs_dir = "$web_path/$dir/$subdirs[2]/obs/$obs_dirs[0]";
        $base_obs_anchor = "
            <a href=web/listgraphs.php/?baseline=$base_title&tbl_hdrs=$obs_hdrs&date=$dir&column1=$dir&path=$base_obs_dir>View Obs Plots</a>";
        $prev_obs_dir = "$web_path/$dir/$subdirs[2]/obs/$obs_dirs[1]";
        $prev_obs_anchor = "
            <a href=web/listgraphs.php/?baseline=$prev_title&tbl_hdrs=$obs_hdrs&date=$dir&column1=$dir&path=$prev_obs_dir>View Obs Plots</a>";
        $color="black";
      }

      // echo out the rows
      echo "
      <tr>
        <td style=color:$color id=$dir > <strong>$dir</strong> </td>
        <td> $base_model_anchor </td>
        <td> $base_obs_anchor </td>
        <td> $prev_model_anchor </td>
        <td> $prev_obs_anchor </td>
      </tr>";

    }
  }
}
?>

<!DOCTYPE html>
<html>
  <head> <title>MPAS-JEDI Weekly Cycling II</title>
    <?php include('inc-meta.php'); ?>

    <!-- meta for social sharing images -->
    <meta property="og:title" content="Prediction, Assimilation &amp; Risk Communication" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="" />
    <meta property="og:description" content="" />
    <meta property="og:image" content="" />
    <meta name="twitter:title" content="Prediction, Assimilation &amp; Risk Communication" />
    <meta name="twitter:description" content="" />
    <meta name="twitter:image" content="" />
    <meta property="og:image:width" content="" />
    <meta property="og:image:height" content="" />
  </head>

  <body class="ncar with-sidebar with-resources">

    <main class="container-lg py-2 pt-md-3">
        <div class="d-grid d-print-flex">
          <nav aria-label="breadcrumb" class="breadcrumb-wrapper mb-2 d-print-none">
            <ol class="breadcrumb">
              <li class="breadcrumb-item"><a href="https://www.mmm.ucar.edu">MMM Home</a></li>
              <li class="breadcrumb-item active" aria-current="page">MPAS-JEDI Weekly Cycling</li>
            </ol>
          </nav>

          <article class="main-content-wrapper">
            <h1>MPAS-JEDI Weekly Cycling</h1>

              <div class="main-content clearfix">
                <div class="resources-main p-3">
                  <div class="mb-3">
                    <h2 class="mb-0">Overview</h2>
                    <p>Part of the PANDA-C project, these plots below show data from our weekly cycling test of the MPAS-JEDI software.</p>
                  </div>

                    <div class="">
                      <h2 class="mb-0">Documentation</h2>
                      <p>View all of the date directories in the table below. Clicking on the
                        <strong>View Plots</strong> links will show graph types for that rows date.</p> 
                      <p></p>
                      <p> View notes about various comparison graphs:
                      <a href="/projects/mpas-jedi/weekly-cycling/web/notes.html"></i> View graph notes</a></p>
                    </div>
                </div>

                  <!-- start of the dir list -->
                <br>
                <table class="table">
                  <thead style="position: sticky; top: 0;">
                    <tr>
                      <th class="sticky-top" scope="col">Date</th>
                      <th class="sticky-top" scope="col">Model Graphs vs baseline</th>
                      <th class="sticky-top" scope="col">Obs Graphs vs baseline</th>
                      <th class="sticky-top" scope="col">Model Graphs vs previous</th>
                      <th class="sticky-top" scope="col">Obs Graphs vs previous</th>
                    </tr>
                  </thead>
                  <tbody>
                    <?php build_date_table(); ?>
                  </tbody>
                </table>
                <hr />

            </div>
          </article>

          <?php include('inc-sidebar.php'); ?>
      </div>
    </main>

    <?php include('inc-js.php'); ?>

  </body>
</html>
